_: {
  dendritic.nixpkgs.allowUnfreePackages = [ "claude-code" ];

  home.base = {
    programs.claude-code = {
      enable = true;
      settings = {
        theme = "dark";
        tui = "fullscreen";
        permissions.defaultMode = "auto";
        sandbox = {
          enabled = true;
          failIfUnavailable = true;
          autoAllowBashIfSandboxed = true;
          allowUnsandboxedCommands = true;
        };
      };
    };
  };
}
