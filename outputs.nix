inputs:
let
  evaluation = inputs.flake-parts.lib.evalFlakeModule { inherit inputs; } {
    imports = [ (inputs.import-tree ./components/nix) ];
  };
in
evaluation.config.processedFlake
