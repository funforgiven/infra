_: {
  home.gui =
    { lib, pkgs, ... }:
    let
      inherit (pkgs) blender python3Packages;
      blenderMcp = python3Packages.buildPythonApplication (finalAttrs: {
        pname = "mcp-for-blender";
        version = "2.3.1";
        pyproject = true;

        src = pkgs.fetchPypi {
          pname = "mcp_for_blender";
          inherit (finalAttrs) version;
          hash = "sha256-B5szQrS81Xd4JsLMoAsfzELWVXYjtkDAdByCaQt1Ebw=";
        };
        build-system = [
          python3Packages.setuptools
          python3Packages.wheel
        ];
        dependencies = [
          python3Packages.httpx
          python3Packages.mcp_1
        ];
        pythonImportsCheck = [ "blender_mcp.server" ];
        meta.mainProgram = "mcp-for-blender";
      });
      blenderVersion = lib.versions.majorMinor blender.version;
    in
    {
      home.packages = [ blender ];
      home.sessionVariables.BLENDERMCP_NO_UPDATE_CHECK = "1";

      xdg.configFile."blender/${blenderVersion}/scripts/addons/blender_mcp.py" = {
        source = "${blenderMcp}/${pkgs.python3.sitePackages}/blender_mcp/bundled/addon.py";
        onChange = ''
          ${lib.getExe blender} --background -noaudio --python-exit-code 1 --python-expr '
          import addon_utils, bpy
          if "blender_mcp" not in bpy.context.preferences.addons:
              if addon_utils.enable("blender_mcp", default_set=True) is None:
                  raise RuntimeError("Could not enable MCP for Blender")
              bpy.ops.wm.save_userpref()
          '
        '';
      };

      programs.codex.settings.mcp_servers.blender = {
        command = lib.getExe blenderMcp;
        env.DISABLE_TELEMETRY = "true";
        default_tools_approval_mode = "prompt";
        tool_timeout_sec = 600;
      };
    };
}
