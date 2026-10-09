-- Temporary isolated Neovim preview; never loaded from the normal user init.
vim.cmd('syntax on')
if vim.env.NTS_SHADOW_COPY then vim.cmd.colorscheme('noctalia-nts')
else dofile(vim.env.NTS_SHADOW_OUTPUT) end
vim.o.number = true
vim.o.cursorline = true
vim.cmd('enew')
vim.bo.filetype = 'markdown'
vim.api.nvim_buf_set_lines(0, 0, -1, false, {
  '# Noctalia shadow preview', '',
  'Independent Markdown, **bold**, *italic*, `inline code`.',
  '[A link](https://example.invalid) and a normal paragraph.',
  '', '```lua', 'local answer = "hello" -- comment', 'return 42', '```',
})
if vim.env.NTS_SHADOW_INTERACTIVE == '1' then
  local function read(path)
    local f = io.open(path, 'rb'); if not f then return nil end
    local text = f:read('*a'); f:close(); return text
  end
  local loaded = vim.fn.sha256(read(vim.env.NTS_SHADOW_COPY))
  local watcher = vim.uv.new_timer()
  watcher:start(1000, 1000, vim.schedule_wrap(function()
    if vim.g.colors_name ~= 'noctalia-nts' then return end
    local text = read(vim.env.NTS_SHADOW_OUTPUT)
    local raw = read(vim.env.NTS_SHADOW_MANIFEST)
    if not text or not raw or #text > 65536 or #raw > 65536 then return end
    local ok, m = pcall(vim.json.decode, raw)
    if not ok or type(m) ~= 'table' or type(m.files) ~= 'table' then return end
    local entry = m.files[vim.env.NTS_SHADOW_OUTPUT]
    local info = vim.uv.fs_lstat(vim.env.NTS_SHADOW_OUTPUT)
    local digest = vim.fn.sha256(text)
    if type(entry) ~= 'table' or not info or info.type ~= 'file' or bit.band(info.mode, 511) ~= entry.installed_mode
        or digest ~= entry.installed_sha256 or digest == loaded then return end
    local output = assert(io.open(vim.env.NTS_SHADOW_COPY, 'wb'))
    output:write(text); output:close()
    vim.cmd.colorscheme('noctalia-nts')
    loaded = digest
  end))
  vim.api.nvim_create_autocmd('VimLeavePre', { callback = function() watcher:stop(); watcher:close() end })
else
  local highlights = {}
  for _, name in ipairs({'Normal', 'NormalFloat', 'Comment', 'String', 'Function', 'Statement',
      'Title', 'Visual', 'Search', 'LineNr', 'StatusLine', 'DiagnosticError'}) do
    highlights[name] = vim.api.nvim_get_hl(0, {name=name, link=false})
  end
  local syntax = {}
  for _, point in ipairs({{1, 3}, {3, 24}, {4, 2}, {7, 1}}) do
    local id = vim.fn.synID(point[1], point[2], 1)
    table.insert(syntax, {group=vim.fn.synIDattr(id, 'name'),
      fg=vim.fn.synIDattr(vim.fn.synIDtrans(id), 'fg#'), bg=vim.fn.synIDattr(vim.fn.synIDtrans(id), 'bg#')})
  end
  io.write(vim.json.encode({isolated=true, colors_name=vim.g.colors_name,
    background=vim.o.background, termguicolors=vim.o.termguicolors, highlights=highlights, markdown_syntax=syntax}))
  vim.cmd('qa!')
end
