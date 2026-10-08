{ config, lib, pkgs, defaultPackage, ... }:
let
  cfg = config.programs.noctalia-theme-sync;
in {
  options.programs.noctalia-theme-sync = {
    enable = lib.mkEnableOption "Noctalia v5 theme-sync CLI";
    package = lib.mkOption { type = lib.types.package; default = defaultPackage; };
    bridge.enable = lib.mkEnableOption "optional loopback JSON/SSE user service";
  };
  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    systemd.user.services.noctalia-theme-sync-bridge = lib.mkIf cfg.bridge.enable {
      description = "Noctalia canonical theme JSON/SSE bridge";
      after = [ "graphical-session.target" ];
      partOf = [ "graphical-session.target" ];
      wantedBy = [ "graphical-session.target" ];
      serviceConfig = {
        ExecStart = "${cfg.package}/bin/noctalia-theme-sync bridge";
        Restart = "on-failure";
        RestartSec = 2;
        UMask = "0077";
        NoNewPrivileges = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
        MemoryMax = "256M";
        TasksMax = 32;
        Environment = [ "PYTHONDONTWRITEBYTECODE=1" "PYTHONUNBUFFERED=1" ];
      };
    };
  };
}
