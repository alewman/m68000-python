/* Force-included (g++ -include) into every WinUAE translation unit of the
   referee build.  WinUAE's CPU tester is written for Windows, where TCHAR is
   wide; on Unix TCHAR is char.  Give wprintf a char overload (libstdc++'s
   <cwchar> undefines a macro of that name) and name the Windows-only mkdir. */
#include <stdio.h>
#include <wchar.h>
#include <sys/stat.h>
#ifdef __cplusplus
int wprintf(const char *format, ...);
#endif
#define _wmkdir(path) mkdir((path), 0777)
