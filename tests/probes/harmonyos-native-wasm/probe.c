#define _GNU_SOURCE
#include <napi/native_api.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static long elapsed(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec*1000L+t.tv_nsec/1000000L; }
static napi_value Run(napi_env env,napi_callback_info info) {
    size_t count=1,length=0; napi_value arg,result; char entry[1024],log[1040],report[256];
    if(napi_get_cb_info(env,info,&count,&arg,NULL,NULL)!=napi_ok || count!=1 ||
       napi_get_value_string_utf8(env,arg,entry,sizeof(entry),&length)!=napi_ok ||
       !length || length>=sizeof(entry)-1 || length!=strlen(entry)) { napi_throw_type_error(env,NULL,"Expected probe entry"); return NULL; }
    snprintf(log,sizeof(log),"%s.log",entry); long started=elapsed(); pid_t owner=getpid(),pid=fork();
    if(pid==0) {
        if(prctl(PR_SET_PDEATHSIG,SIGKILL,0,0,0)<0 || getppid()!=owner) _exit(125);
        int output=open(log,O_WRONLY|O_CREAT|O_TRUNC,0600);
        if(output<0 || dup2(output,1)<0 || dup2(output,2)<0) _exit(126);
        syscall(SYS_close_range,3u,~0u,0u);
        setenv("UV_USE_IO_URING","0",1);
        void *library=dlopen("libnode.so",RTLD_NOW|RTLD_LOCAL);
        typedef int (*Start)(int,char **); Start start=library?(Start)dlsym(library,"_ZN4node5StartEiPPc"):NULL;
        if(!start) {fprintf(stderr,"Node loader failed: %s\n",dlerror());_exit(127);}
        char *args[]={"node","--max-old-space-size=512",entry,NULL}; _exit(start(3,args));
    }
    int status=0,waiting=0,timedout=0;
    if(pid>0) {
        while((waiting=waitpid(pid,&status,WNOHANG))==0 || (waiting<0 && errno==EINTR)) {
            if(elapsed()-started>15000) {kill(pid,SIGKILL);while(waitpid(pid,&status,0)<0 && errno==EINTR) {} timedout=1;break;}
            usleep(10000);
        }
    }
    snprintf(report,sizeof(report),"{\"pid\":%d,\"exitCode\":%d,\"signal\":%d,\"timedOut\":%s,\"elapsedMs\":%ld}",
      pid,pid>0&&WIFEXITED(status)?WEXITSTATUS(status):-1,pid>0&&WIFSIGNALED(status)?WTERMSIG(status):0,timedout?"true":"false",elapsed()-started);
    napi_create_string_utf8(env,report,NAPI_AUTO_LENGTH,&result);return result;
}
static napi_value Init(napi_env env,napi_value exports) {
    napi_property_descriptor descriptor={"run",NULL,Run,NULL,NULL,NULL,napi_default,NULL};
    napi_define_properties(env,exports,1,&descriptor);return exports;
}
static napi_module module={.nm_version=1,.nm_register_func=Init,.nm_modname="poc"};
__attribute__((constructor))static void Register(void){napi_module_register(&module);}
