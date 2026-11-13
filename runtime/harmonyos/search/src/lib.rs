use ignore::{overrides::OverrideBuilder, WalkBuilder};
use regex::bytes::Regex;
use serde_json::{json, Value};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU8, Ordering};

const VCS: [&str; 6] = [".git", ".svn", ".hg", ".bzr", ".jj", ".sl"];

enum Failure {
    Pattern(String),
    Io(String),
    Overflow,
    Aborted,
}

impl From<std::io::Error> for Failure {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.to_string())
    }
}

fn check_cancel(cancel: &AtomicU8) -> Result<(), Failure> {
    if cancel.load(Ordering::Acquire) != 0 {
        return Err(Failure::Aborted);
    }
    Ok(())
}

fn append(output: &mut String, line: &str, max: usize) -> Result<(), Failure> {
    if output.len() + line.len() + 1 > max {
        return Err(Failure::Overflow);
    }
    output.push_str(line);
    output.push('\n');
    Ok(())
}

fn relative_path(path: &Path, workdir: &Path) -> Result<String, Failure> {
    path.strip_prefix(workdir)
        .unwrap_or(path)
        .to_str()
        .filter(|text| !text.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| Failure::Io("Unsupported file name".into()))
}

fn grep_file(
    path: &Path,
    display: &str,
    pattern: &Regex,
    output: &mut String,
    max: usize,
    cancel: &AtomicU8,
) -> Result<(), Failure> {
    let mut reader = BufReader::new(File::open(path)?);
    let mut line = Vec::new();
    let start = output.len();
    let mut line_number = 0;
    loop {
        check_cancel(cancel)?;
        line.clear();
        let mut oversized = false;
        loop {
            let data = reader.fill_buf()?;
            if data.is_empty() {
                break;
            }
            let newline = data.iter().position(|byte| *byte == b'\n');
            let count = newline.map_or(data.len(), |at| at + 1);
            if data[..count].contains(&0) {
                output.truncate(start);
                return Ok(());
            }
            if line.len() + count > max {
                oversized = true;
            } else if !oversized {
                line.extend_from_slice(&data[..count]);
            }
            reader.consume(count);
            check_cancel(cancel)?;
            if newline.is_some() {
                break;
            }
        }
        if oversized {
            return Err(Failure::Overflow);
        }
        if line.is_empty() {
            return Ok(());
        }
        line_number += 1;
        let content = line.strip_suffix(b"\n").unwrap_or(&line);
        if pattern.is_match(content) {
            let lines = match std::str::from_utf8(&line) {
                Ok(text) => json!({ "text": text }),
                Err(_) => json!({ "bytes": "" }),
            };
            let record = json!({ "type": "match", "data": {
                "path": { "text": display }, "line_number": line_number, "lines": lines
            } });
            append(output, &record.to_string(), max)?;
        }
    }
}

fn run(request: &Value, cancel: &AtomicU8) -> Result<String, Failure> {
    let string = |name: &str| {
        request[name]
            .as_str()
            .ok_or_else(|| Failure::Io("Invalid search request".into()))
    };
    let workdir = PathBuf::from(string("workdir")?);
    let target = PathBuf::from(string("target")?);
    let glob = string("tool")? == "glob";
    let pattern = if glob {
        None
    } else {
        Some(Regex::new(string("pattern")?).map_err(|error| Failure::Pattern(error.to_string()))?)
    };
    let cap = request["cap"]
        .as_u64()
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| Failure::Io("Invalid search output cap".into()))?;
    let mut overrides = OverrideBuilder::new(&workdir);
    if let Some(filter) = request["filter"].as_str() {
        overrides
            .add(filter)
            .map_err(|error| Failure::Pattern(error.to_string()))?;
    }
    let mut walker = WalkBuilder::new(&target);
    walker
        .hidden(!glob)
        .ignore(!glob)
        .git_ignore(!glob)
        .git_global(false)
        .git_exclude(!glob)
        .parents(!glob)
        .follow_links(false)
        .overrides(
            overrides
                .build()
                .map_err(|error| Failure::Pattern(error.to_string()))?,
        )
        .filter_entry(|entry| !VCS.iter().any(|name| entry.file_name() == *name));
    let mut output = String::new();
    for entry in walker.build() {
        check_cancel(cancel)?;
        let entry = entry.map_err(|error| Failure::Io(error.to_string()))?;
        if !entry.file_type().is_some_and(|kind| kind.is_file()) {
            continue;
        }
        let display = relative_path(entry.path(), &workdir)?;
        if let Some(pattern) = &pattern {
            grep_file(entry.path(), &display, pattern, &mut output, cap, cancel)?;
        } else {
            if display.contains('\n') {
                return Err(Failure::Io("File name contains a line break".into()));
            }
            append(&mut output, &display, cap)?;
        }
    }
    Ok(output)
}

// The caller pins both byte buffers until the asynchronous operation completes.
#[no_mangle]
pub unsafe extern "C" fn dsh_search(
    bytes: *const u8,
    length: usize,
    cancelled: *const AtomicU8,
    result_size: *mut usize,
) -> *mut u8 {
    let request = serde_json::from_slice(std::slice::from_raw_parts(bytes, length));
    let response = match request {
        Ok(request) => match run(&request, &*cancelled) {
            Ok(stdout) => json!({ "stdout": stdout }),
            Err(Failure::Pattern(message)) => {
                json!({ "error": "SEARCH_INVALID_PATTERN", "message": message })
            }
            Err(Failure::Io(message)) => json!({ "error": "SEARCH_FAILED", "message": message }),
            Err(Failure::Overflow) => {
                json!({ "error": "SEARCH_RAW_OUTPUT_OVERFLOW", "message": "Search output exceeds its limit" })
            }
            Err(Failure::Aborted) => {
                json!({ "error": "SEARCH_ABORTED", "message": "Search was cancelled" })
            }
        },
        Err(_) => json!({ "error": "SEARCH_FAILED", "message": "Invalid search request" }),
    };
    let response = response.to_string().into_bytes().into_boxed_slice();
    *result_size = response.len();
    Box::into_raw(response) as *mut u8
}

#[no_mangle]
pub unsafe extern "C" fn dsh_search_free(bytes: *mut u8, length: usize) {
    drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(
        bytes, length,
    )));
}
