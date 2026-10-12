{ pkgs, backend }:
let
  executable = pkgs.runCommand "forge-cache-backend-13.1.0-isolation.1" { } ''
    install -Dm755 ${backend} "$out/bin/forgejo-runner"
  '';
  tools = pkgs.buildEnv {
    name = "forge-cache-tools";
    paths = [
      executable
      pkgs.python3
      pkgs.cacert
    ];
    pathsToLink = [
      "/bin"
      "/etc/ssl"
    ];
  };
  root = pkgs.runCommand "forge-cache-root" { } ''
    mkdir -p "$out/etc" "$out/tmp" "$out/var/lib/forge-cache"
    printf '%s\n' 'cache:x:1000:1000:Cache:/var/lib/forge-cache:/bin/false' > "$out/etc/passwd"
    printf '%s\n' 'cache:x:1000:' > "$out/etc/group"
  '';
in
pkgs.dockerTools.buildLayeredImage {
  name = "git.fahrican.com/forge-runner/cache";
  tag = "13.1.0-isolation.1";
  contents = [
    tools
    root
  ];
  fakeRootCommands = ''
    chmod 1777 tmp
    chown 1000:1000 var/lib/forge-cache
  '';
  config = {
    User = "1000:1000";
    WorkingDir = "/var/lib/forge-cache";
    Env = [
      "PATH=/bin"
      "HOME=/var/lib/forge-cache"
      "PYTHONDONTWRITEBYTECODE=1"
    ];
    Cmd = [
      "/bin/forgejo-runner"
      "--version"
    ];
    Labels = {
      "org.opencontainers.image.source" = "https://github.com/funforgiven/infra";
      "org.opencontainers.image.description" =
        "Private Forgejo build cache backend with scoped cache isolation fixes";
    };
  };
}
