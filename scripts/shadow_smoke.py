#!/usr/bin/env python3
"""Native parity proof, intended for a namespace with isolated HOME/XDG/IPC.

No desktop IPC commands, wallpaper changes, native activation or real init files.
--visual uses a private Xvfb and Kitty; never binds the user's display.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from noctalia_theme_sync import adapters, cli


def call(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(args)
    if code:
        raise RuntimeError('shadow command failed: ' + args[0])
    return json.loads(out.getvalue())


def run(argv, **kwargs):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=25, **kwargs)
    if p.returncode:
        raise RuntimeError(p.stderr[:1000])
    return p


def visual(root, themes):
    # The smoke must already be inside an isolated filesystem/network namespace.
    if Path('/run/user').exists() or any(os.environ.get(k) for k in ('DISPLAY', 'WAYLAND_DISPLAY', 'NIRI_SOCKET',
                                                                    'DBUS_SESSION_BUS_ADDRESS')):
        raise ValueError('visual verification requires isolated IPC and no real display')
    fb = root / 'framebuffer'
    fb.mkdir()
    server = subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1024x720x24', '-fbdir', str(fb),
                               '-nolisten', 'tcp', '-ac'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    program = root / 'visual.lua'
    program.write_text('''
vim.cmd('syntax on')
vim.g.markdown_fenced_languages = {'lua'}
dofile(vim.env.NTS_THEME)
vim.o.number = true
vim.o.cursorline = true
vim.o.laststatus = 2
vim.o.statusline = ' Noctalia parity: Markdown | Lua '
vim.cmd('enew')
vim.bo.filetype = 'markdown'
vim.api.nvim_buf_set_lines(0, 0, -1, false, {
  '# Heading', '', '## Markdown appearance', '',
  '**Bold**, *italic*, `inline code`', '[Link](https://example.invalid)', '',
  '> A quotation', '', '- List item', '', '```lua', 'local n = 42', '```'
})
vim.cmd('vsplit')
vim.cmd('enew')
vim.bo.filetype = 'lua'
vim.api.nvim_buf_set_lines(0, 0, -1, false, {
  '-- Syntax highlighting', '', 'local message = "hello"', 'local answer = 42', '',
  'local function greet(name)', '  if name then', '    return message .. name', '  end', 'end', '',
  'print(greet("Noctalia"))'
})
vim.defer_fn(function()
  vim.fn.writefile({vim.json.encode({name=vim.g.colors_name, background=vim.o.background,
    normal=vim.api.nvim_get_hl(0, {name='Normal', link=false}),
    func=vim.api.nvim_get_hl(0, {name='Function', link=false})})}, vim.env.NTS_READY)
end, 500)
''')
    shots = []
    try:
        for _ in range(100):
            if (fb / 'Xvfb_screen0').exists():
                break
            if server.poll() is not None:
                raise RuntimeError('Xvfb failed')
            time.sleep(.05)
        for name, theme in themes:
            ready = root / (name + '.ready')
            colors = re.search(r'"Normal", \{ fg = "(#[0-9a-fA-F]{6})", bg = "(#[0-9a-fA-F]{6})"', theme.read_text())
            if not colors:
                raise ValueError('expected explicit Normal foreground/background')
            env = dict(os.environ, DISPLAY=':99', KITTY_DISABLE_WAYLAND='1', LIBGL_ALWAYS_SOFTWARE='1',
                       NTS_THEME=str(theme), NTS_READY=str(ready), NVIM_NOTTYFAST='1')
            # This fixed-background fixture needs no startup terminal queries.
            # Nvim documents NVIM_NOTTYFAST for slow DSR responses (E1568).
            with (root / (name + '.terminal.log')).open('w') as log:
                proc = subprocess.Popen(['kitty', '--config', 'NONE', '--title', 'Noctalia shadow proof',
                    '-o', 'font_size=13', '-o', 'remember_window_size=no', '-o', 'initial_window_width=1000',
                    '-o', 'initial_window_height=680', '-o', 'cursor_blink_interval=0',
                    '-o', 'background=' + colors[2], '-o', 'foreground=' + colors[1],
                    '-o', 'enable_audio_bell=no', 'nvim', '-u', 'NONE', '-i', 'NONE', '-n',
                    '-c', 'lua dofile(' + json.dumps(str(program)) + ')'], env=env,
                    stdout=log, stderr=log, start_new_session=True)
                try:
                    for _ in range(200):
                        if ready.exists():
                            break
                        if proc.poll() is not None:
                            raise RuntimeError('isolated Kitty exited: ' + (root / (name + '.terminal.log')).read_text()[-1000:])
                        time.sleep(.05)
                    if not ready.exists():
                        raise RuntimeError('isolated Neovim did not become ready')
                    actual = json.loads(ready.read_text())
                    assert actual['normal']['bg'] == int(colors[2][1:], 16), actual
                    assert actual['normal']['fg'] == int(colors[1][1:], 16), actual
                    time.sleep(.3)
                    shot = root / (name + '.png')
                    run(['magick', 'xwd:' + str(fb / 'Xvfb_screen0'), str(shot)])
                    shots.append(shot)
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=10)
    finally:
        server.terminate()
        server.wait(timeout=10)
    from PIL import Image, ImageChops
    pairs = []
    for a, b in zip(shots[::2], shots[1::2]):
        first, second = Image.open(a).convert('RGB'), Image.open(b).convert('RGB')
        same = ImageChops.difference(first, second).getbbox() is None
        pairs.append({'reference': a.name, 'shadow': b.name, 'pixel_equal': same})
    return pairs


def require_pixel_parity(pairs):
    if not pairs or any(p.get('pixel_equal') is not True for p in pairs):
        raise ValueError('native screenshot mismatch; inspect retained evidence')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--reference', type=Path, help='trusted personal template, read only')
    parser.add_argument('--palette', action='append', type=Path, default=[], help='additional canonical snapshot, read only')
    parser.add_argument('--visual', action='store_true')
    args = parser.parse_args()
    root = args.output
    root.mkdir(mode=0o700)  # Never replace old evidence.
    reference = args.reference or Path(str(adapters.assets().joinpath('adapters/neovim.lua')))
    records, themes = [], []
    fixtures = Path(__file__).resolve().parents[1] / 'tests/fixtures'
    cases = [(m + '-' + a, fixtures / (m + '-' + a + '.json'))
             for m, a in (('dark', 'green'), ('light', 'purple'), ('dark', 'purple'), ('light', 'green'))]
    cases += [('existing-' + str(i), p) for i, p in enumerate(args.palette)]
    for label, canonical in cases:
        p = json.loads(canonical.read_text())
        mode = p['mode']
        theme = root / (label + '-tokens.json')
        # Explicit conversion: canonical envelope is NOT Noctalia --theme-json.
        theme.write_text(json.dumps({mode: p['colors']}))
        native = root / (label + '-personal.lua')
        command = ['noctalia', 'theme', '--theme-json', str(theme), '--' + mode,
                   '--default-mode', mode, '--render', str(reference) + ':' + str(native)]
        run(command)
        trial = root / (label + '-trial')
        plan = root / (label + '-plan.json')
        call('shadow', 'plan', '--root', str(trial), '--palette', str(canonical), '--write-plan', str(plan))
        call('shadow', 'install', '--root', str(trial), '--palette', str(canonical), '--from-plan', str(plan))
        output = trial / 'config/nvim/colors/noctalia-nts.lua'
        equivalent = native.read_bytes().replace(b'colors_name = "noctalia"', b'colors_name = "noctalia-nts"')
        assert output.read_bytes() == equivalent
        preview = call('shadow', 'test', '--root', str(trial))
        assert preview['background'] == mode and preview['termguicolors']
        assert preview['highlights']['Normal']['bg'] == int(p['colors']['surface'][1:], 16)
        assert preview['highlights']['String']['fg'] == int(p['colors']['secondary'][1:], 16)
        assert preview['highlights']['Function']['fg'] == int(p['colors']['primary'][1:], 16)
        script = adapters.assets().joinpath('shadow-neovim.lua').read_text().replace("dofile(vim.env.NTS_SHADOW_OUTPUT)",
                                                                               'dofile(' + json.dumps(str(native)) + ')')
        test = root / (label + '-personal-test.lua')
        test.write_text(script)
        # Isolated HOME/XDG are supplied by the smoke runner; no normal init.
        reference_preview = json.loads(run(['nvim', '--headless', '-u', 'NONE', '-i', 'NONE', '-n',
                                 '-c', 'lua dofile(' + json.dumps(str(test)) + ')']).stdout)
        assert preview['highlights'] == reference_preview['highlights']
        assert preview['markdown_syntax'] == reference_preview['markdown_syntax']
        assert any(s['group'] for s in preview['markdown_syntax'])
        records.append({'palette': label, 'byte_parity_except_identity': True,
                        'native_highlight_and_markdown_parity': True, 'preview': preview,
                        'shadow_sha256': hashlib.sha256(output.read_bytes()).hexdigest()})
        themes += [(label + '-personal', native), (label + '-shadow', output)]
    if args.visual:
        pixels = visual(root, themes)
    else:
        pixels = 'not performed'
    # Direct canonical input behavior is tested, never assumed compatible.
    raw = subprocess.run(['noctalia', 'theme', '--theme-json', str(fixtures / 'dark-green.json'),
                 '--dark', '--render', str(reference)+':'+str(root / 'unconverted.lua')], capture_output=True, text=True)
    for _, output in themes[1::2]:
        trial = output.parents[3]
        call('shadow', 'rollback', '--root', str(trial))
        assert not output.exists()
    result = {'palettes': records, 'visual': pixels, 'unconverted_canonical': {'exit_code': raw.returncode,
                'stderr': raw.stderr}, 'rollback': 'passed', 'production_activation': False}
    (root / 'result.json').write_text(json.dumps(result, indent=2))
    if args.visual:
        require_pixel_parity(pixels)  # Evidence and rollback precede a failed gate.
    print(json.dumps({'palettes': len(records), 'visual': pixels, 'rollback': 'passed'}))


if __name__ == '__main__':
    main()
