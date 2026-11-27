"""Unified CLI for SD3 Preset Forge."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from sd3_forge.analyze_bounce import run_analysis
from sd3_forge.calibrate import run_calibration
from sd3_forge.compile_sd3p import compile_blueprint_to_sd3p
from sd3_forge.daemon import (
    daemon_status,
    render_via_daemon_or_direct,
    start_daemon_background,
    stop_daemon,
)
from sd3_forge.extract_gt import extract_inventory_to_file
from sd3_forge.generate_test_midi import VALID_SCOPES, generate_midi_and_manifest
from sd3_forge.init_workspace import run_init
from sd3_forge.inventory_cli import (
    load_inventory,
    query_fx,
    query_keymap,
    query_kits,
    query_mics,
    query_pieces,
    query_stacks,
    query_summary,
)
from sd3_forge.migrate import migrate_blueprint_file
from sd3_forge.paths import load_package_text
from sd3_forge.profile_ref import profile_reference_wav
from sd3_forge.validate_blueprint import validate_preset_dir


def cmd_init(args: argparse.Namespace) -> int:
    result = run_init(
        sd3_path=args.sd3_path,
        vst3_path=args.vst3_path,
        presets_dir=args.presets_dir,
        from_vst3=args.from_vst3,
        generate_midi_files=not args.no_midi,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"OK: Initialized SD3 Preset Forge config at {result['config_path']}")
        print(f"    Inventory:     {result['inventory_path']}")
        print(f"    Base template: {result['base_template_path']} ({result['base_template_source']})")
        if result["midi_path"]:
            print(f"    Test MIDI:     {result['midi_path']}")
    return 0


def cmd_extract_gt(args: argparse.Namespace) -> int:
    out_file = extract_inventory_to_file(sd3_path=args.sd3_path, out_path=args.out_file)
    print(f"OK: Ground Truth extracted to {out_file}")
    return 0


def cmd_generate_midi(args: argparse.Namespace) -> int:
    midi_path, manifest_path = generate_midi_and_manifest(args.out_dir, scope=args.scope)
    print(f"OK: Generated {midi_path} and {manifest_path}")
    return 0


def cmd_new_preset(args: argparse.Namespace) -> int:
    preset_dir = Path("presets") / args.genre / args.slug
    (preset_dir / "bounces").mkdir(parents=True, exist_ok=True)
    (preset_dir / "bounces" / ".gitkeep").write_text("", encoding="utf-8")

    def _read_tpl(fname: str) -> str | None:
        try:
            return load_package_text(f"templates/{fname}")
        except Exception:
            local = Path("templates") / fname
            return local.read_text(encoding="utf-8") if local.exists() else None

    spec_dst = preset_dir / "02-spec-targets.yaml"
    bp_dst = preset_dir / "03-sd3-blueprint.yaml"
    spec_tpl = _read_tpl("02-spec-targets.template.yaml")
    if not spec_dst.exists() and spec_tpl is not None:
        content = spec_tpl.replace("{{PRESET_ID}}", args.slug).replace("{{GENRE}}", args.genre)
        spec_dst.write_text(content, encoding="utf-8")
    bp_tpl = _read_tpl("03-sd3-blueprint.template.yaml")
    if not bp_dst.exists() and bp_tpl is not None:
        content = bp_tpl.replace("{{PRESET_ID}}", args.slug).replace("{{GENRE}}", args.genre)
        bp_dst.write_text(content, encoding="utf-8")

    research = preset_dir / "01-research.md"
    if not research.exists():
        research.write_text(
            f"# Reference Research — {args.slug} ({args.genre})\n\n"
            "> Mark facts as `[Verified Source]` or `[Acoustic Inference]`.\n",
            encoding="utf-8",
        )
    cal_log = preset_dir / "04-calibration-log.md"
    if not cal_log.exists():
        cal_log.write_text(
            f"# Calibration Log — {args.slug}\n\nAwaiting `bounces/v1.wav`.\n",
            encoding="utf-8",
        )
    print(f"OK: Scaffolded preset at {preset_dir}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    res = validate_preset_dir(args.preset_dir, inventory_path=args.inventory)
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
        return 0 if res.ok else 1

    for w in res.warnings:
        print(f"WARN: {w}")
    if res.errors:
        for e in res.errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print(f"FAIL: {args.preset_dir} ({len(res.errors)} error(s))", file=sys.stderr)
        return 1
    print(f"PASS: {args.preset_dir} validated against Ground Truth (0 errors).")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    report = run_analysis(
        args.preset_dir,
        args.wav_path,
        manifest_path=args.manifest,
        align=not args.no_align,
    )
    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["overall_status"] == "PASS" else 1

    s = report["summary"]
    print(
        f"{report['overall_status']}: {report['preset_id']} — "
        f"{s['passed']}/{s['total_checks']} PASS, {s['warnings']} WARN, {s['hard_failures']} FAIL"
    )
    for c in report["checks"]:
        if c["status"] != "PASS":
            print(f"  [{c['status']}] {c['metric']}: {c['measured']} {c['unit']} -> {c['guidance']}")
    return 0 if report["overall_status"] == "PASS" else 1


def cmd_compile_sd3p(args: argparse.Namespace) -> int:
    out_path = compile_blueprint_to_sd3p(
        args.preset_dir,
        out_path=args.out,
        template_path=args.template,
        inventory_path=args.inventory,
        install_to_sd3=args.install,
        install_name=args.install_name,
    )
    print(f"OK: Compiled .sd3p preset to {out_path}")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    result = migrate_blueprint_file(
        args.target,
        out_path=args.out,
        in_place=args.in_place,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        dst = result["out_path"] or result["source_path"]
        print(f"OK: Migrated blueprint to schema_version 2.0 -> {dst}")
    return 0


def cmd_profile_ref(args: argparse.Namespace) -> int:
    profile = profile_reference_wav(args.wav_path)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(profile, indent=2, ensure_ascii=False))
    else:
        tp = profile["transient_priors"]
        ld = profile["loudness"]
        print(
            f"ADVISORY PROFILE ({profile['file_name']}): "
            f"Kick~{tp['kick_fundamental_hz']} Hz, Snare~{tp['snare_fundamental_hz']} Hz, "
            f"LUFS={ld['integrated_lufs']} (conf={tp['confidence']})"
        )
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    inv, resolved = load_inventory(args.inventory)
    subcmd = args.inv_command
    if subcmd == "summary":
        payload = query_summary(inv)
        payload["inventory_path"] = str(resolved)
    elif subcmd == "kits":
        payload = query_kits(inv, kit_name=args.kit)
    elif subcmd == "pieces":
        payload = query_pieces(inv, slot=args.slot, search=args.search, limit=args.limit)
    elif subcmd == "mics":
        payload = query_mics(inv, bleed_only=args.bleed_only, include_unavailable=args.all)
    elif subcmd == "fx":
        payload = query_fx(inv, category=args.category, search=args.search, name=args.name)
    elif subcmd == "stacks":
        payload = query_stacks(inv, category=args.category, search=args.search, limit=args.limit)
    elif subcmd == "keymap":
        payload = query_keymap(inv, group=args.group, search=args.search)
    else:
        raise ValueError(f"Unsupported inventory query {subcmd!r}")

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if subcmd == "summary":
        c = payload["counts"]
        print(
            f"Inventory: {payload.get('library')} ({resolved})\n"
            f"  Kits: {c['base_kits']} | Slots: {c['slots']} | Installed Mics: {c['installed_mics']}/{c['total_mics']} | "
            f"FX: {c['native_fx']} | Stacks: {c['stack_items']} | MIDI Notes: {c['midi_notes']}"
        )
    elif subcmd == "kits":
        if "kit" in payload:
            kit = payload["kit"]
            print(f"Kit: {kit['name']}")
            for sl, nm in kit.get("pieces", {}).items():
                print(f"  {sl}: {nm}")
        else:
            for nm in payload["base_kits"]:
                print(f"- {nm}")
    elif subcmd == "pieces":
        print(f"Matches: {payload['total_matches']} (truncated={payload['truncated']})")
        for p in payload["pieces"]:
            print(f"  [{p['slot']}] {p['name']}")
    elif subcmd == "mics":
        for m in payload["mics"]:
            flags = [k for k in ("stereo", "bleedcontrol", "ambient") if m.get(k)]
            print(f"  {m['mixname']} ({', '.join(flags) or 'mono'})")
    elif subcmd == "fx":
        if "effect" in payload:
            ef = payload["effect"]
            print(f"FX #{ef['effect_id']} {ef['name']} [{ef['category']}] — {ef['model_inspiration']}")
            for prm in payload["params"]:
                print(f"  [{prm['index']}] {prm['name']} ({prm['unit']}) aliases={prm['aliases']}")
        else:
            for item in payload["fx"]:
                print(f"  #{item['effect_id']} {item['name']} [{item['category']}]: {', '.join(item['controls'])}")
    elif subcmd == "stacks":
        for cat, items in payload["stacks"].items():
            print(f"[{cat}]")
            for it in items:
                print(f"  - {it['name']}")
    elif subcmd == "keymap":
        for row in payload["keymap"]:
            print(f"  {row.get('note')}: {row.get('instrument')} — {row.get('articulation')} ({row.get('group')})")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    info = render_via_daemon_or_direct(
        args.sd3p_path,
        args.out_wav,
        midi_path=args.midi,
        vst3_path=args.vst3,
        sample_rate=args.sr,
        tail_seconds=args.tail,
        use_daemon=not args.no_daemon,
    )
    via = " [daemon]" if info.get("via_daemon") else ""
    print(
        f"OK: Rendered{via} {info['out_wav']} ({info['duration_s']:.1f}s @ {info['sample_rate']} Hz, "
        f"peak {info['peak_dbfs']:.2f} dBFS, {info['render_time_s']:.1f}s render)"
    )
    return 0


def cmd_auto_test(args: argparse.Namespace) -> int:
    res = validate_preset_dir(args.preset_dir, inventory_path=args.inventory)
    if not res.ok:
        for e in res.errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    sd3p_path = compile_blueprint_to_sd3p(
        args.preset_dir,
        template_path=args.template,
        inventory_path=args.inventory,
        install_to_sd3=args.install,
    )
    wav_path = args.preset_dir / "bounces" / f"{args.version}.wav"
    info = render_via_daemon_or_direct(
        sd3p_path,
        wav_path,
        midi_path=args.midi,
        vst3_path=args.vst3,
        tail_seconds=args.tail,
        use_daemon=not args.no_daemon,
    )
    via = " [daemon]" if info.get("via_daemon") else ""
    print(
        f"RENDER{via}: {sd3p_path.name} -> {wav_path} "
        f"(peak {info['peak_dbfs']:.2f} dBFS, {info['render_time_s']:.1f}s)"
    )
    report = run_analysis(
        args.preset_dir,
        wav_path,
        manifest_path=args.manifest,
        align=not args.no_align,
    )
    s = report["summary"]
    print(
        f"{report['overall_status']}: {report['preset_id']} ({args.version}) — "
        f"{s['passed']}/{s['total_checks']} PASS, {s['warnings']} WARN, {s['hard_failures']} FAIL"
    )
    for c in report["checks"]:
        if c["status"] != "PASS":
            print(f"  [{c['status']}] {c['metric']}: {c['measured']} {c['unit']} -> {c['guidance']}")
    return 0 if report["overall_status"] == "PASS" else 1


def cmd_daemon(args: argparse.Namespace) -> int:
    if args.daemon_command == "start":
        res = start_daemon_background(vst3_path=args.vst3, idle_timeout_s=args.idle_timeout)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"OK: SD3 daemon running on 127.0.0.1:{res['port']} (pid={res['pid']})")
        return 0
    if args.daemon_command == "status":
        res = daemon_status()
        if args.json:
            print(json.dumps(res, indent=2))
        elif res.get("running"):
            print(
                f"RUNNING: 127.0.0.1:{res['port']} (pid={res['pid']}, renders={res['renders']}, "
                f"idle={res['idle_s']}s/{res['idle_timeout_s']}s)"
            )
        else:
            print("STOPPED: No active SD3 daemon.")
        return 0
    if args.daemon_command == "stop":
        res = stop_daemon()
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print("OK: SD3 daemon stopped." if res["stopped"] else "OK: No running SD3 daemon.")
        return 0
    raise ValueError(f"Unsupported daemon command {args.daemon_command!r}")


def cmd_calibrate(args: argparse.Namespace) -> int:
    res = run_calibration(
        args.preset_dir,
        max_pitch_iters=args.max_pitch_iters,
        max_mix_iters=args.max_mix_iters,
        inventory_path=args.inventory,
        template_path=args.template,
        vst3_path=args.vst3,
        use_daemon=not args.no_daemon,
        run_canary=not args.skip_canary,
    )
    rep = res["final_report"]
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        s = rep["summary"]
        print(
            f"{rep['overall_status']}: {rep['preset_id']} calibrated in {len(res['iterations'])} iter(s) "
            f"(rolled_back={res['rolled_back']}) — {s['passed']}/{s['total_checks']} PASS, "
            f"{s['warnings']} WARN, {s['hard_failures']} FAIL, loss={rep['scalar_loss']}"
        )
        for c in rep["checks"]:
            if c["status"] != "PASS":
                print(f"  [{c['status']}] {c['metric']}: {c['measured']} {c['unit']} -> {c['guidance']}")
    return 0 if rep["overall_status"] == "PASS" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sd3-forge", description="SD3 Preset Forge CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize local SD3 Ground Truth, neutral template, and test MIDI")
    p_init.add_argument("--sd3-path", type=Path, default=None)
    p_init.add_argument("--vst3-path", type=Path, default=None)
    p_init.add_argument("--presets-dir", type=Path, default=None)
    p_init.add_argument("--from-vst3", action="store_true", help="Capture default state from SD3 VST3 before normalizing")
    p_init.add_argument("--no-midi", action="store_true")
    p_init.add_argument("--json", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_gt = sub.add_parser("extract-gt", help="Extract local SD3 Ground Truth inventory.json")
    p_gt.add_argument("--sd3-path", type=Path, default=None)
    p_gt.add_argument("--out-file", type=Path, default=None)
    p_gt.set_defaults(func=cmd_extract_gt)

    p_mid = sub.add_parser("generate-midi", help="Generate standard-test-groove.mid and manifest (or scoped probe)")
    p_mid.add_argument("--out-dir", type=Path, default=None)
    p_mid.add_argument("--scope", choices=VALID_SCOPES, default="full")
    p_mid.set_defaults(func=cmd_generate_midi)

    p_new = sub.add_parser("new-preset", help="Create scaffold for a new preset")
    p_new.add_argument("genre")
    p_new.add_argument("slug")
    p_new.set_defaults(func=cmd_new_preset)

    p_val = sub.add_parser("validate", help="Validate spec targets and blueprint against Ground Truth")
    p_val.add_argument("preset_dir", type=Path)
    p_val.add_argument("--inventory", type=Path, default=None)
    p_val.add_argument("--json", action="store_true")
    p_val.set_defaults(func=cmd_validate)

    p_ana = sub.add_parser("analyze", help="Analyze bounced WAV against spec targets")
    p_ana.add_argument("preset_dir", type=Path)
    p_ana.add_argument("wav_path", type=Path)
    p_ana.add_argument("--manifest", type=Path, default=None)
    p_ana.add_argument("--no-align", action="store_true")
    p_ana.add_argument("--json", action="store_true")
    p_ana.set_defaults(func=cmd_analyze)

    p_cmp = sub.add_parser("compile-sd3p", help="Compile validated 03-sd3-blueprint.yaml into .sd3p")
    p_cmp.add_argument("preset_dir", type=Path)
    p_cmp.add_argument("--out", type=Path, default=None)
    p_cmp.add_argument("--template", type=Path, default=None)
    p_cmp.add_argument("--inventory", type=Path, default=None)
    p_cmp.add_argument("--install", action="store_true", help="Copy compiled .sd3p to SD3 user presets directory")
    p_cmp.add_argument("--install-name", type=str, default=None)
    p_cmp.set_defaults(func=cmd_compile_sd3p)

    p_mig = sub.add_parser("migrate", help="Migrate a v1 blueprint YAML to schema_version '2.0'")
    p_mig.add_argument("target", type=Path, help="Preset directory or 03-sd3-blueprint.yaml path")
    p_mig.add_argument("--out", type=Path, default=None)
    p_mig.add_argument("--in-place", action="store_true")
    p_mig.add_argument("--json", action="store_true")
    p_mig.set_defaults(func=cmd_migrate)

    p_prof = sub.add_parser("profile-ref", help="Extract lightweight advisory priors from a reference drum WAV")
    p_prof.add_argument("wav_path", type=Path)
    p_prof.add_argument("--out", type=Path, default=None)
    p_prof.add_argument("--json", action="store_true")
    p_prof.set_defaults(func=cmd_profile_ref)

    p_inv = sub.add_parser("inventory", help="Compact filtered queries over local Ground Truth inventory.json")
    inv_sub = p_inv.add_subparsers(dest="inv_command", required=True)
    inv_common = argparse.ArgumentParser(add_help=False)
    inv_common.add_argument("--inventory", type=Path, default=None)
    inv_common.add_argument("--json", action="store_true")

    p_inv_sum = inv_sub.add_parser("summary", parents=[inv_common], help="Inventory counts and metadata")
    p_inv_sum.set_defaults(func=cmd_inventory)

    p_inv_kits = inv_sub.add_parser("kits", parents=[inv_common], help="List base kits or inspect --kit")
    p_inv_kits.add_argument("--kit", type=str, default=None)
    p_inv_kits.set_defaults(func=cmd_inventory)

    p_inv_pcs = inv_sub.add_parser("pieces", parents=[inv_common], help="Query kit pieces by --slot / --search")
    p_inv_pcs.add_argument("--slot", type=str, default=None)
    p_inv_pcs.add_argument("--search", type=str, default=None)
    p_inv_pcs.add_argument("--limit", type=int, default=50)
    p_inv_pcs.set_defaults(func=cmd_inventory)

    p_inv_mics = inv_sub.add_parser("mics", parents=[inv_common], help="List installed mixer channels")
    p_inv_mics.add_argument("--bleed-only", action="store_true")
    p_inv_mics.add_argument("--all", action="store_true")
    p_inv_mics.set_defaults(func=cmd_inventory)

    p_inv_fx = inv_sub.add_parser("fx", parents=[inv_common], help="Query 35 native FX or inspect --name")
    p_inv_fx.add_argument("--category", type=str, default=None)
    p_inv_fx.add_argument("--search", type=str, default=None)
    p_inv_fx.add_argument("--name", type=str, default=None)
    p_inv_fx.set_defaults(func=cmd_inventory)

    p_inv_stk = inv_sub.add_parser("stacks", parents=[inv_common], help="Query Stack Pack categories and items")
    p_inv_stk.add_argument("--category", type=str, default=None)
    p_inv_stk.add_argument("--search", type=str, default=None)
    p_inv_stk.add_argument("--limit", type=int, default=50)
    p_inv_stk.set_defaults(func=cmd_inventory)

    p_inv_km = inv_sub.add_parser("keymap", parents=[inv_common], help="Query SD3 MIDI keymap notes")
    p_inv_km.add_argument("--group", type=str, default=None)
    p_inv_km.add_argument("--search", type=str, default=None)
    p_inv_km.set_defaults(func=cmd_inventory)

    p_rnd = sub.add_parser("render", help="Render .sd3p preset offline through SD3 VST3")
    p_rnd.add_argument("sd3p_path", type=Path)
    p_rnd.add_argument("out_wav", type=Path)
    p_rnd.add_argument("--midi", type=Path, default=None)
    p_rnd.add_argument("--vst3", type=Path, default=None)
    p_rnd.add_argument("--sr", type=int, default=44100)
    p_rnd.add_argument("--tail", type=float, default=4.0)
    p_rnd.add_argument("--no-daemon", action="store_true")
    p_rnd.set_defaults(func=cmd_render)

    p_auto = sub.add_parser("auto-test", help="Autonomous validate -> compile-sd3p -> render -> analyze")
    p_auto.add_argument("preset_dir", type=Path)
    p_auto.add_argument("--version", type=str, default="v-auto")
    p_auto.add_argument("--template", type=Path, default=None)
    p_auto.add_argument("--inventory", type=Path, default=None)
    p_auto.add_argument("--midi", type=Path, default=None)
    p_auto.add_argument("--manifest", type=Path, default=None)
    p_auto.add_argument("--vst3", type=Path, default=None)
    p_auto.add_argument("--tail", type=float, default=4.0)
    p_auto.add_argument("--install", action="store_true")
    p_auto.add_argument("--no-align", action="store_true")
    p_auto.add_argument("--no-daemon", action="store_true")
    p_auto.set_defaults(func=cmd_auto_test)

    p_dmn = sub.add_parser("daemon", help="Manage persistent headless VST3 daemon worker")
    dmn_sub = p_dmn.add_subparsers(dest="daemon_command", required=True)
    p_dmn_start = dmn_sub.add_parser("start", help="Start background VST3 worker")
    p_dmn_start.add_argument("--vst3", type=Path, default=None)
    p_dmn_start.add_argument("--idle-timeout", type=float, default=900.0)
    p_dmn_start.add_argument("--json", action="store_true")
    p_dmn_start.set_defaults(func=cmd_daemon)

    p_dmn_st = dmn_sub.add_parser("status", help="Show persistent VST3 daemon status")
    p_dmn_st.add_argument("--json", action="store_true")
    p_dmn_st.set_defaults(func=cmd_daemon)

    p_dmn_stop = dmn_sub.add_parser("stop", help="Stop persistent VST3 daemon")
    p_dmn_stop.add_argument("--json", action="store_true")
    p_dmn_stop.set_defaults(func=cmd_daemon)

    p_cal = sub.add_parser("calibrate", help="Run bounded 2-stage analytical calibrator with auto-rollback")
    p_cal.add_argument("preset_dir", type=Path)
    p_cal.add_argument("--max-pitch-iters", type=int, default=3)
    p_cal.add_argument("--max-mix-iters", type=int, default=4)
    p_cal.add_argument("--inventory", type=Path, default=None)
    p_cal.add_argument("--template", type=Path, default=None)
    p_cal.add_argument("--vst3", type=Path, default=None)
    p_cal.add_argument("--no-daemon", action="store_true")
    p_cal.add_argument("--skip-canary", action="store_true")
    p_cal.add_argument("--json", action="store_true")
    p_cal.set_defaults(func=cmd_calibrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
