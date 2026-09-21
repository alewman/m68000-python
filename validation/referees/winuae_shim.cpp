// Unix stand-ins for the few od-win32/unicode.cpp helpers WinUAE's CPU tester
// and gencpu call.  Our code, not WinUAE's.
#include <ctype.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

char *ua(const char *s) { return strdup(s); }
char *ua_copy(char *dst, int maxlen, const char *src) { snprintf(dst, maxlen, "%s", src); return dst; }
int uaetcslen(const char *s) { return (int)strlen(s); }
void to_lower(char *s, int len) { for (int i = 0; s[i] && (len < 0 || i < len); i++) s[i] = tolower((unsigned char)s[i]); }
void to_upper(char *s, int len) { for (int i = 0; s[i] && (len < 0 || i < len); i++) s[i] = toupper((unsigned char)s[i]); }
int wprintf(const char *format, ...)
{
	va_list a;
	va_start(a, format);
	int n = vfprintf(stderr, format, a);
	va_end(a);
	return n;
}
