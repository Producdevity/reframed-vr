#include <string.h>

int __system_property_get(const char *name, char *value)
{
    if (!strcmp(name, "failure"))
        return -7;
    strcpy(value, !strcmp(name, "fallback") ? "fallback-value" : "original");
    return (int)strlen(value);
}
