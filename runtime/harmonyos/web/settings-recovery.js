// This code runs inside the bundled DSH General Settings module.
function MobileHarnessNavigationRow(title, description, action, destination) {
	const css = DeveloperToolsRow_module_css_default;
	return react_jsx_runtime.jsxs("div", {
		className: css.row,
		children: [
			react_jsx_runtime.jsxs("div", {
				children: [
					react_jsx_runtime.jsx("div", {
						className: css.title,
						children: title,
					}),
					react_jsx_runtime.jsx("div", {
						className: css.description,
						children: description,
					}),
				],
			}),
			react_jsx_runtime.jsx(_deepseek_ai_dsh_client_ui_primitives.Button, {
				variant: "outline",
				size: "sm",
				onClick: () => window.location.assign(destination),
				children: action,
			}),
		],
	});
}

function MobileHarnessRecoveryRow() {
	const chinese = document.documentElement.lang.startsWith("zh");
	return MobileHarnessNavigationRow(chinese ? "运行时恢复" : "Runtime recovery",
		chinese ? "以安全模式或正常模式重新打开应用。" : "Reopen the app in safe or normal mode.",
		chinese ? "恢复选项" : "Recovery options", "/.mobile-harness/recovery");
}

function MobileHarnessGitHubRow() {
	const chinese = document.documentElement.lang.startsWith("zh");
	return MobileHarnessNavigationRow(chinese ? "Forge GitHub 账号" : "Forge GitHub account",
		chinese ? "管理此设备的 GitHub 授权。" : "Manage GitHub authorization on this device.",
		chinese ? "管理账号" : "Manage account", "/.mobile-harness/github");
}

function MobileHarnessRemoteRow() {
	const chinese = document.documentElement.lang.startsWith("zh");
	return MobileHarnessNavigationRow(chinese ? "远程主机" : "Remote hosts",
		chinese ? "连接电脑或服务器上的 DSH Web。" : "Connect to DSH Web on a computer or server.",
		chinese ? "管理主机" : "Manage hosts", "/.mobile-harness/remote");
}

function registerMobileHarnessRecovery(ctx) {
	ctx.slots.inject("settings.general.item", () => ctx.slots.register({
		name: "settings.general.item",
		id: "mobile-harness-remote",
		order: 96,
		locale: NS,
	}, MobileHarnessRemoteRow));
	ctx.slots.inject("settings.general.item", () => ctx.slots.register({
		name: "settings.general.item",
		id: "mobile-harness-github",
		order: 97,
		locale: NS,
	}, MobileHarnessGitHubRow));
	ctx.slots.inject("settings.general.item", () => ctx.slots.register({
		name: "settings.general.item",
		id: "mobile-harness-recovery",
		order: 98,
		locale: NS,
	}, MobileHarnessRecoveryRow));
}
