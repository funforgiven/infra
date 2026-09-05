#!/bin/sh
set -eu
until test -s /restore/.database-verified; do sleep 2; done
test -d /restore/data/git/repositories/forge-runner/runner-qualification.git
for owner in /restore/data/git/repositories/*; do
  for repository in "$owner"/*.git; do
    test -d "$repository" || continue
    git --git-dir="$repository" fsck --full --strict
  done
done
git --git-dir=/restore/data/git/repositories/forge-runner/runner-qualification.git \
  rev-parse --verify refs/heads/main
cp /restore/.database-verified /restore/.qualified
printf '%s\n' 'Restored Git object graphs and the qualification branch verified.'
while :; do sleep 3600; done
