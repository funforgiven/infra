_: {
  perSystem =
    { pkgs, self', ... }:
    {
      checks = {
        wow-addons = pkgs.runCommandLocal "wow-addons-check" { nativeBuildInputs = [ pkgs.python3 ]; } ''
          python ${../battle-net/validate_addons.py} \
            ${../battle-net/addons.lock.json} ${self'.packages.wow-addons}
          touch "$out"
        '';
        wow-addon-credentials =
          pkgs.runCommandLocal "wow-addon-credentials-check"
            {
              nativeBuildInputs = [
                pkgs.age
                pkgs.sops
                pkgs.python3
                pkgs.instawow
              ];
            }
            ''
              export PYTHONDONTWRITEBYTECODE=1
              python -m unittest discover -s ${../battle-net} -p 'test_*.py' -v

              export XDG_CONFIG_HOME="$TMPDIR/config"
              export XDG_CACHE_HOME="$TMPDIR/cache"
              export XDG_STATE_HOME="$TMPDIR/state"
              mkdir -p "$XDG_CONFIG_HOME/instawow/profiles/forever" "$TMPDIR/AddOns"
              cat > "$XDG_CONFIG_HOME/instawow/profiles/forever/config.json" <<EOF
              {"profile":"forever","addon_dir":"$TMPDIR/AddOns","flavour_override":"forever_classic"}
              EOF
              test "$(instawow -p forever list --format json)" = '[]'
              touch "$out"
            '';
      };
    };
}
