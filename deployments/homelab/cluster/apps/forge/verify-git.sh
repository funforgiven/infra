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
atollion=/restore/data/git/repositories/funforgiven/atollion.git
test -s /restore/.atollion-main-ancestors
test -s /restore/.atollion-required-commits
while IFS= read -r commit; do
  git --git-dir="$atollion" merge-base --is-ancestor "$commit" refs/heads/main
done < /restore/.atollion-main-ancestors
while IFS= read -r commit; do
  git --git-dir="$atollion" cat-file -e "$commit^{commit}"
done < /restore/.atollion-required-commits
cp /restore/.database-verified /restore/.qualified
printf '%s\n' 'Restored Git object graphs, Atollion source/cutover ancestry, historical PR commits and qualification branch verified.'
while :; do sleep 3600; done
