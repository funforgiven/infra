{ lib, ... }:
{
  options.repository.thirdPartyNotices = lib.mkOption {
    type = lib.types.lines;
    readOnly = true;
    default = builtins.readFile ../../../THIRD_PARTY_NOTICES.md;
    description = "THIRD_PARTY_NOTICES.md, also bundled with the desktop shell.";
  };
}
