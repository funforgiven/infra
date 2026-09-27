_: {
  home.gui =
    { config, lib, ... }:
    let
      outputs = lib.throwIfNot (
        config.dendritic.niri.outputs != null
      ) "The GUI profile requires host-specific Niri output facts." config.dendritic.niri.outputs;
    in
    {
      programs.niri.settings.workspaces = {
        "01-chat" = {
          name = "chat";
          open-on-output = outputs.portrait.identifier;
        };
        "03-steam" = {
          name = "steam";
          open-on-output = outputs.primary.identifier;
        };
      };
    };
}
