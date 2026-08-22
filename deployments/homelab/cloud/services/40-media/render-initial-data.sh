#!/bin/sh
set -eu
umask 077

admin_password="$(cat /run/source/sftpgo-admin-password)"
user_password="$(cat /run/source/sftpgo-user-password)"

case "$admin_password" in
  *[!A-Za-z0-9_-]*|"") exit 1 ;;
esac
case "$user_password" in
  *[!A-Za-z0-9_-]*|"") exit 1 ;;
esac
test "${#admin_password}" -ge 32
test "${#user_password}" -ge 32

mkdir -p /srv/sftpgo/data/media/library

{
  printf '{"users":[{'
  printf '"status":1,"username":"music-library",'
  printf '"password":"%s",' "$user_password"
  printf '"home_dir":"/srv/sftpgo/data/media/library",'
  printf '"uid":1000,"gid":1000,'
  printf '"permissions":{"/":["*"]}'
  printf '}],"admins":[{'
  printf '"status":1,"username":"admin",'
  printf '"password":"%s",' "$admin_password"
  printf '"permissions":["*"]'
  printf '}]}\n'
} > /run/rendered/initial-data.json
unset admin_password user_password
