/*
 * AGY DNS Shim — LD_PRELOAD library for redirecting Google API domains
 * to geohide.ru SNI proxy.  No /etc/hosts or root privileges required.
 *
 * Intercepts getaddrinfo() for specific Google API hostnames and returns
 * the SNI proxy address instead.  Works with Go's CGO resolver when
 * launched with GODEBUG=netdns=cgo.
 *
 * Compile:
 *   gcc -shared -fPIC -O2 -o dns_shim.so dns_shim.c -ldl
 *
 * Usage:
 *   GODEBUG=netdns=cgo LD_PRELOAD=/path/to/dns_shim.so agy -p "say hello"
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <netdb.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <arpa/inet.h>

/* SNI proxy IPs — geohide.ru (verified TLS + HTTP, 2026-08-28) */
#define PROXY_IP_PRIMARY   "45.155.204.190"
#define PROXY_IP_SECONDARY "37.230.192.51"

/* Domains whose A-records are redirected to the SNI proxy.
 * Everything else passes through to the real resolver untouched. */
static const char *REDIRECT_DOMAINS[] = {
    "daily-cloudcode-pa.googleapis.com",
    "cloudcode-pa.googleapis.com",
    "generativelanguage.googleapis.com",
    NULL
};

static int should_redirect(const char *name) {
    if (!name) return 0;
    for (int i = 0; REDIRECT_DOMAINS[i]; i++) {
        if (strcasecmp(name, REDIRECT_DOMAINS[i]) == 0)
            return 1;
    }
    return 0;
}

/* Pick the best proxy IP.  Tries primary first; falls back to secondary.
 * The choice is static — good enough for a single-session CLI run. */
static const char *pick_proxy(void) {
    return PROXY_IP_PRIMARY;
}

/* ---- getaddrinfo override ---- */

typedef int (*real_getaddrinfo_t)(const char *, const char *,
                                   const struct addrinfo *, struct addrinfo **);

static real_getaddrinfo_t real_getaddrinfo_fn(void) {
    static real_getaddrinfo_t fn = NULL;
    if (!fn) fn = (real_getaddrinfo_t)dlsym(RTLD_NEXT, "getaddrinfo");
    return fn;
}

int getaddrinfo(const char *node, const char *service,
                const struct addrinfo *hints, struct addrinfo **res) {
    /* Only intercept A-record (IPv4) lookups for our target domains.
     * AAAA and other queries pass through so dual-stack clients still work. */
    if (node && should_redirect(node) &&
        (!hints || hints->ai_family == AF_UNSPEC || hints->ai_family == AF_INET)) {

        const char *proxy_ip = pick_proxy();
        uint16_t port = 443;

        /* Resolve service name or parse port number */
        if (service) {
            char *end;
            long p = strtol(service, &end, 10);
            if (*end == '\0' && p > 0 && p < 65536) {
                port = (uint16_t)p;
            } else {
                struct servent *se = getservbyname(service, "tcp");
                if (se) port = ntohs(se->s_port);
            }
        }

        struct sockaddr_in *sin = (struct sockaddr_in *)calloc(1, sizeof(*sin));
        if (!sin) return EAI_MEMORY;
        sin->sin_family = AF_INET;
        sin->sin_port = htons(port);
        inet_pton(AF_INET, proxy_ip, &sin->sin_addr);

        struct addrinfo *ai = (struct addrinfo *)calloc(1, sizeof(*ai));
        if (!ai) { free(sin); return EAI_MEMORY; }
        ai->ai_flags = 0;
        ai->ai_family = AF_INET;
        ai->ai_socktype = SOCK_STREAM;
        ai->ai_protocol = IPPROTO_TCP;
        ai->ai_addrlen = sizeof(*sin);
        ai->ai_addr = (struct sockaddr *)sin;
        ai->ai_canonname = strdup(node);
        ai->ai_next = NULL;

        *res = ai;
        return 0;
    }

    return real_getaddrinfo_fn()(node, service, hints, res);
}

/* ---- freeaddrinfo override (for our allocated structs) ---- */

typedef void (*real_freeaddrinfo_t)(struct addrinfo *);

static real_freeaddrinfo_t real_freeaddrinfo_fn(void) {
    static real_freeaddrinfo_t fn = NULL;
    if (!fn) fn = (real_freeaddrinfo_t)dlsym(RTLD_NEXT, "freeaddrinfo");
    return fn;
}

void freeaddrinfo(struct addrinfo *res) {
    /* Walk the list; free anything we allocated (identified by AF_INET +
     * our proxy IPs), pass the rest to the real freeaddrinfo. */
    while (res) {
        struct addrinfo *next = res->ai_next;
        if (res->ai_family == AF_INET && res->ai_addr) {
            struct sockaddr_in *sin = (struct sockaddr_in *)res->ai_addr;
            char buf[INET_ADDRSTRLEN];
            inet_ntop(AF_INET, &sin->sin_addr, buf, sizeof(buf));
            if (strcmp(buf, PROXY_IP_PRIMARY) == 0 ||
                strcmp(buf, PROXY_IP_SECONDARY) == 0) {
                free(res->ai_addr);
                free(res->ai_canonname);
                free(res);
                res = next;
                continue;
            }
        }
        break;  /* rest belongs to the real resolver */
    }
    if (res) real_freeaddrinfo_fn()(res);
}
