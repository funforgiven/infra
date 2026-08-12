# fahrican.routeros

This source-local collection layers the repository's narrowly scoped terminal
compatibility on top of `ansible.netcommon` 8.6.0 and `community.routeros`
3.21.0 from the flake-locked Ansible runtime. It is not an independent
RouterOS module collection.

RouterOS 7.21.5 can issue the ECMA-48 cursor-position query `ESC[6n` while an
interactive SSH shell is opening. The upstream `community.routeros` terminal
plugin strips that sequence as ANSI before `network_cli` can answer it. This
collection preserves the query until its initial-login handler sees
it and replies with `ESC[1;1R`, without a trailing carriage return. The older
RouterOS terminal-identification query `ESC Z` remains supported regardless of
which query arrives first. Once the shell prompt is established, the adapter
restores the upstream prompt handler; cliconf is always redirected to
`community.routeros.routeros`.
