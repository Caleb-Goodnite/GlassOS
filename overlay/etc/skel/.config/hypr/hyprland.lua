-- GlassOS desktop (Hyprland) - "Prism" design language
-- This file is yours: edit it and save, Hyprland reloads it live.
-- Docs: https://wiki.hypr.land/Configuring/Start/

-------------------------------------------------------------------------------
-- Machine-specific tweaks written at login by /usr/bin/glass-session
-- (e.g. software cursors inside virtual machines). Safe if missing.
-- Optional files are only loaded if they exist (a missing one is not an error).
local hypr_dir = (os.getenv("XDG_CONFIG_HOME") or (os.getenv("HOME") .. "/.config")) .. "/hypr/"
local function optional(name)
    local f = io.open(hypr_dir .. name .. ".lua", "r")
    if not f then return nil end
    f:close()
    package.loaded[name] = nil
    local ok, result = pcall(require, name)
    if ok then return result end
    return nil
end

local M = optional("machine")
if type(M) ~= "table" then M = {} end
-- M.light: no graphics acceleration, so the glass only blurs the wallpaper (cheap, cached)
-- instead of re-blurring every window behind it on every frame

-- What you chose in the Settings app (Settings writes ~/.config/hypr/glass-settings.lua;
-- put your own changes in custom.lua instead, since Settings rewrites that file).
local S = optional("glass-settings")
if type(S) ~= "table" then S = {} end
local function pick(v, default) if v == nil then return default end return v end

-------------------------------------------------------------------------------
-- Apps
local terminal    = "glass-launch foot"
local files       = "glass-launch thunar"
local browser     = "glass-launch glass-browser"
local settings    = "glass-launch glass-settings"
local lens        = "glass-launch glass-lens"
local launcher    = "pkill -x fuzzel || (glass-sound launcher; fuzzel)"

-------------------------------------------------------------------------------
-- Displays
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = "auto" })
for _, m in ipairs(S.monitors or {}) do hl.monitor(m) end

-- Brightness for screens without a backlight (virtual machines, most external monitors): the
-- brightness slider dims the picture instead, with a screen shader that glasshw.py writes
-- (~/.config/hypr/glass-dim.lua names it). Full brightness turns the shader off.
local D = optional("glass-dim")
if type(D) == "table" and D.shader then
    local f = io.open(D.shader, "r")
    if f then f:close(); hl.config({ decoration = { screen_shader = D.shader } }) end
end

-------------------------------------------------------------------------------
-- Session start: everything GlassOS runs in your session is in this one script.
hl.on("hyprland.start", function()
    hl.exec_cmd("/usr/lib/glassos/session-start")
end)

-- UI sounds (silent if your sound pack has no file for them, or if you mute them)
hl.on("window.open",      function() hl.exec_cmd("glass-sound window-open") end)
hl.on("window.close",     function() hl.exec_cmd("glass-sound window-close") end)
hl.on("workspace.active", function() hl.exec_cmd("glass-sound workspace") end)

-------------------------------------------------------------------------------
-- Environment
hl.env("XCURSOR_THEME", "Bibata-Modern-Ice")
hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")
hl.env("QT_QPA_PLATFORM", "wayland;xcb")
hl.env("MOZ_ENABLE_WAYLAND", "1")
hl.env("GDK_BACKEND", "wayland,x11")
-- Every window gets a title bar with the red/yellow/green buttons from the hyprbars plugin (see
-- "Title bars" below). Only if the plugin is missing do older (GTK 3) apps like Files and Text
-- Editor draw their own title bar instead, so every window still has one to drag and close.
local hyprbars_so = "/usr/lib/glassos/hyprland/libhyprbars.so"
local have_hyprbars = io.open(hyprbars_so, "r")
if have_hyprbars then have_hyprbars:close() else hl.env("GTK_CSD", "1") end

-------------------------------------------------------------------------------
-- Look and feel: frosted glass, soft depth, continuous ("squircle") corners
--
-- How the glass layers: every window's blur samples what is really behind it, other windows
-- included (xray = false). One window over the wallpaper is lightly frosted, so you can still
-- make out shapes behind it; a window on top of that one blurs and tints the already-frosted
-- window again, so looking through two or three panes gets progressively frostier and darker.
hl.config({
    general = {
        gaps_in  = 6,
        gaps_out = 14,
        border_size = 1,
        col = {
            -- a thin specular rim, as on macOS Golden Gate's glass: brightest on the top-left where
            -- the light hits, dim along the sides, and catching light again at the bottom-right
            -- where it passes back out through the glass
            active_border   = { colors = { "rgba(ffffff8c)", "rgba(ffffff1c)", "rgba(ffffff14)", "rgba(ffffff4a)" }, angle = 135 },
            inactive_border = { colors = { "rgba(ffffff3c)", "rgba(ffffff0c)", "rgba(ffffff0a)", "rgba(ffffff22)" }, angle = 135 },
        },
        resize_on_border = true,
        extend_border_grab_area = 12,
        hover_icon_on_border = true,
        layout = "dwindle",
        snap = { enabled = true, window_gap = 10, monitor_gap = 10 },
    },

    decoration = {
        rounding       = 20,
        rounding_power = 4.0,      -- squircle corners: the curve eases in, unlike a circle
        active_opacity   = 1.0,
        inactive_opacity = 1.0,

        shadow = {
            enabled      = not M.light,
            range        = 36,
            render_power = 3,
            offset       = "0 10",
            color        = 0x66000000,
            color_inactive = 0x33000000,
        },

        -- Settings > Appearance > Glass slides all of these together, from Clear (a light blur that
        -- keeps shapes and colour behind) to Frosted (a heavy, grainy blur). The defaults here are
        -- the slider's default position; glassui.glass_look() has the whole range.
        blur = {
            enabled   = true,
            size      = M.light and 4 or pick(S.frost_size, 5),
            passes    = M.light and 1 or pick(S.frost_passes, 2),
            noise     = pick(S.frost_noise, 0.012),
            contrast  = 1.0,
            brightness = pick(S.frost_brightness, 0.67),  -- darkens what shows through, so white text stays readable over white pages
            vibrancy  = pick(S.frost_vibrancy, 0.59),     -- keeps the wallpaper's colour in the glass
            vibrancy_darkness = 0.4,                       -- ...in its dark parts too, not just the bright ones
            popups    = true,
            popups_ignorealpha = 0.5,   -- blur only behind a menu itself, not the see-through space around its rounded corners
            new_optimizations = true,
            xray      = M.light or false,
        },

        dim_inactive = false,
    },

    animations = { enabled = true },

    input = {
        kb_layout = pick(S.kb_layout, "us"),
        kb_variant = pick(S.kb_variant, ""),
        -- click to focus, like a Mac: pointing at a window doesn't steal focus, but scrolling
        -- still reaches whatever is under the pointer
        follow_mouse = 2,
        sensitivity = pick(S.sensitivity, 0),
        natural_scroll = pick(S.mouse_natural_scroll, false),
        touchpad = {
            natural_scroll = pick(S.touchpad_natural_scroll, true),
            tap_to_click = pick(S.tap_to_click, true),
            disable_while_typing = true,
            clickfinger_behavior = true,
        },
    },

    dwindle = { preserve_split = true },

    misc = {
        force_default_wallpaper = 0,
        disable_hyprland_logo   = true,
        disable_splash_rendering = true,
        focus_on_activate = true,
        animate_manual_resizes = true,
        enable_anr_dialog = true,
    },

    -- hide Hyprland's own splash text and update notices
    ecosystem = {
        no_update_news  = true,
        no_donation_nag = true,
    },

    cursor = { inactive_timeout = 0 },
})

-- Springy, fluid motion
hl.curve("glass",   { type = "bezier", points = { {0.16, 1}, {0.3, 1} } })
hl.curve("smooth",  { type = "bezier", points = { {0.25, 0.1}, {0.25, 1} } })
hl.curve("linear",  { type = "bezier", points = { {0, 0}, {1, 1} } })
hl.curve("float",   { type = "spring", mass = 1, stiffness = 90, dampening = 15 })

hl.animation({ leaf = "global",        enabled = true, speed = 8,   bezier = "smooth" })
hl.animation({ leaf = "windowsIn",     enabled = true, speed = 4.2, spring = "float", style = "popin 90%" })
hl.animation({ leaf = "windowsOut",    enabled = true, speed = 2.2, bezier = "glass", style = "popin 92%" })
hl.animation({ leaf = "windowsMove",   enabled = true, speed = 4.5, spring = "float" })
hl.animation({ leaf = "border",        enabled = true, speed = 6,   bezier = "glass" })
hl.animation({ leaf = "fade",          enabled = true, speed = 3,   bezier = "smooth" })
hl.animation({ leaf = "layersIn",      enabled = true, speed = 3.2, bezier = "glass", style = "popin 94%" })
hl.animation({ leaf = "layersOut",     enabled = true, speed = 1.8, bezier = "glass", style = "fade" })
hl.animation({ leaf = "workspaces",    enabled = true, speed = 4.5, bezier = "glass", style = "slide" })

-------------------------------------------------------------------------------
-- Windows float by default (like a classic desktop). Press Super+T to tile/untile the
-- active window into a neat grid with the other tiled windows.
hl.window_rule({
    name  = "glass-float-by-default",
    match = { class = ".*" },
    float = true,
})

-- No window opens bigger than the screen (it can still be made bigger by hand)
hl.window_rule({
    name     = "glass-fit-screen",
    match    = { class = ".*" },
    max_size = "monitor_w*0.96 monitor_h*0.86",
})

-- Keep windows on the screen. When you let go of the mouse after moving or resizing a window
-- (title bar, Super+drag or an edge), it slides back so all of it is on screen and its top
-- sits below the top bar, so its title bar can always be grabbed. A window bigger than the
-- screen shrinks to fit. Clicking a window that's already out of place fixes it too.
local function vec(v)
    if type(v) ~= "table" then return nil end
    return v.x or v[1], v.y or v[2]
end

-- The part of a screen windows live in: the whole screen minus the top bar (and, with
-- avoid_dock, minus the dock at the bottom, for windows snapped to half the screen)
local function work_area(m, avoid_dock)
    local mw, mh = m.width / m.scale, m.height / m.scale
    if m.transform % 2 == 1 then mw, mh = mh, mw end
    local left, top, right, bottom = m.x, m.y, m.x + mw, m.y + mh
    for _, l in ipairs(hl.get_layers()) do
        if l.monitor and l.monitor.id == m.id then
            if l.namespace == "waybar" and l.y < m.y + mh / 2 then
                top = math.max(top, l.y + l.h + 6)
            elseif avoid_dock and l.namespace == "glass-dock" and l.y > m.y + mh / 2 then
                bottom = math.min(bottom, l.y - 6)
            end
        end
    end
    return left, top, right, bottom
end

local function keep_on_screen(w)
    if not w or not w.floating or w.fullscreen ~= 0 or not w.monitor then return end
    local left, top, right, bottom = work_area(w.monitor)
    local x, y = vec(w.at)
    local ww, wh = vec(w.size)
    if not x or not ww then return end
    local nw, nh = math.min(ww, right - left), math.min(wh, bottom - top)
    if nw ~= ww or nh ~= wh then
        hl.dispatch(hl.dsp.window.resize({ x = math.floor(nw), y = math.floor(nh), exact = true, window = "address:" .. w.address }))
    end
    local nx = math.max(left, math.min(x, right - nw))
    local ny = math.max(top, math.min(y, bottom - nh))
    if nx ~= x or ny ~= y then
        hl.dispatch(hl.dsp.window.move({ x = math.floor(nx), y = math.floor(ny), window = "address:" .. w.address }))
    end
end

-- Split screen: drag a window until the pointer touches the left or right edge of the screen
-- and let go, and it fills that half (Super+Left / Super+Right do the same). Drag it away from
-- the edge and it gets its old size back.
local snapped = {}   -- address -> { w, h, side, x, y } (its size before snapping, and where it snapped to)

local function snap(w, side)
    if not w or not w.monitor then return end
    if w.fullscreen ~= 0 then
        hl.dispatch(hl.dsp.window.fullscreen_state({ internal = 0, client = 0, window = "address:" .. w.address }))
    end
    if not w.floating then hl.dispatch(hl.dsp.window.float({ action = "set", window = "address:" .. w.address })) end
    local left, top, right, bottom = work_area(w.monitor, true)
    local gap = 8
    local half = math.floor((right - left - 3 * gap) / 2)
    local x = side == "left" and left + gap or left + 2 * gap + half
    -- the hyprbars title bar sits above the window's own top edge (GlassOS apps draw theirs inside)
    local bar = (hl.plugin.hyprbars and not tostring(w.class or ""):match("^os%.glass%.")) and 34 or 0
    local y, h = top + bar, math.floor(bottom - top - bar)
    local prev = snapped[w.address]
    local ww, wh = vec(w.size)
    snapped[w.address] = { w = prev and prev.w or ww, h = prev and prev.h or wh, side = side, x = math.floor(x), y = math.floor(y) }
    local sel = "address:" .. w.address
    hl.dispatch(hl.dsp.window.resize({ x = half, y = h, exact = true, window = sel }))
    hl.dispatch(hl.dsp.window.move({ x = math.floor(x), y = math.floor(y), window = sel }))
end

-- Back to the size it had before snapping, keeping it under the pointer
local function unsnap(w, cursor)
    local s = w and snapped[w.address]
    if not s then return end
    snapped[w.address] = nil
    local sel = "address:" .. w.address
    hl.dispatch(hl.dsp.window.resize({ x = math.floor(s.w), y = math.floor(s.h), exact = true, window = sel }))
    if cursor then
        hl.dispatch(hl.dsp.window.move({ x = math.floor(cursor.x - s.w / 2), y = math.floor(cursor.y - 15), window = sel }))
    end
end

-- A left-button press remembers where the window was, so letting go can tell a drag from a click
local press = nil
hl.bind("mouse:272", function()
    local w = hl.get_active_window()
    local x, y
    if w then x, y = vec(w.at) end   -- (`w and vec()` would keep only x)
    press = w and { address = w.address, x = x, y = y } or nil
end, { non_consuming = true, ignore_mods = true })

hl.bind("mouse:272", function()
    local w = hl.get_active_window()
    local p = press
    press = nil
    if not w then return end
    local x, y = vec(w.at)
    local moved = p and p.address == w.address and x and (math.abs(x - p.x) > 3 or math.abs(y - p.y) > 3)
    local cursor = hl.get_cursor_pos()
    if moved and cursor and w.monitor and w.floating and w.fullscreen == 0 then
        local m = w.monitor
        local mw = (m.transform % 2 == 1 and m.height or m.width) / m.scale
        if cursor.x <= m.x + 8 then snap(w, "left") return end
        if cursor.x >= m.x + mw - 8 then snap(w, "right") return end
        local s = snapped[w.address]
        if s and (x ~= s.x or y ~= s.y) then unsnap(w, cursor) end
    end
    keep_on_screen(hl.get_active_window())
end, { release = true, non_consuming = true, ignore_mods = true })

-- forget windows that close
hl.on("window.close", function(w) if w and w.address then snapped[w.address] = nil end end)

-- Make full size (the maximize button, or double-clicking a title bar) works like full screen
-- on a Mac: the window covers the whole screen and the top bar and dock get out of the way. The
-- app still thinks it's only maximized, so it keeps its title bar and the button to shrink back.
local function set_fullscreen(addr, internal, client)
    hl.dispatch(hl.dsp.window.fullscreen_state({ internal = internal, client = client, window = "address:" .. addr }))
end

-- Hyprland sends no event when the app asks to shrink back, so while a window is full size a
-- timer checks it 4 times a second; it stops when no window is full size
local full_size = {}
local watch
watch = hl.timer(function()
    for addr in pairs(full_size) do
        local w = hl.get_window("address:" .. addr)
        if not w or w.fullscreen ~= 2 then
            full_size[addr] = nil                       -- closed, or Super+F took it out
        elseif w.fullscreen_client == 0 then
            full_size[addr] = nil                       -- the app asked to shrink back
            set_fullscreen(addr, 0, 0)
        end
    end
    if next(full_size) == nil then watch:set_enabled(false) end
end, { timeout = 250, type = "repeat" })
watch:set_enabled(false)

hl.on("window.fullscreen", function(w)
    w = w or hl.get_active_window()
    -- the app asked to be maximized (client 1); a zoom (below) is maximized with client 0
    if w and w.fullscreen == 1 and w.fullscreen_client == 1 then
        set_fullscreen(w.address, 2, 1)
        full_size[w.address] = true
        watch:set_enabled(true)
    end
end)

-------------------------------------------------------------------------------
-- Title bars: Mac-style red, yellow and green buttons on every window
--
-- The buttons run `hyprctl eval 'glass_window("...")'`, which calls this function. It acts on
-- the focused window: clicking a button focuses its window first.
--   "close"    red: closes the window
--   "minimize" yellow: hides it on the "minimized" desktop; click its app in the dock to get it back
--   "full"     green: full size (covers the top bar and dock) and back
--   "zoom"     a double-click on the title bar: fill the space between the top bar and the dock,
--              and back, like double-clicking a title bar on a Mac
--   "center"   move it to the middle of the screen
-- An optional second argument names a window by address (the top bar's window menu uses it).
function glass_window(action, address)
    local w = address and hl.get_window("address:" .. address) or hl.get_active_window()
    if not w then return end
    local sel = "address:" .. w.address
    if action == "close" then
        hl.dispatch(hl.dsp.window.close({ window = sel }))
    elseif action == "minimize" then
        hl.dispatch(hl.dsp.window.move({ workspace = "special:minimized", follow = false, window = sel }))
    elseif action == "full" then
        if w.fullscreen ~= 0 then
            full_size[w.address] = nil
            set_fullscreen(w.address, 0, 0)
        else
            set_fullscreen(w.address, 2, 1)               -- same full size as an app's own maximize
            full_size[w.address] = true
            watch:set_enabled(true)
        end
    elseif action == "zoom" then
        full_size[w.address] = nil
        set_fullscreen(w.address, w.fullscreen == 0 and 1 or 0, 0)
    elseif action == "center" then
        if not w.floating then hl.dispatch(hl.dsp.window.float({ action = "set", window = sel })) end
        if w.fullscreen ~= 0 then full_size[w.address] = nil; set_fullscreen(w.address, 0, 0) end
        local ww, wh = vec(w.size)
        if w.monitor and ww then
            local left, top, right, bottom = work_area(w.monitor, true)
            local nw, nh = math.min(ww, right - left), math.min(wh, bottom - top)
            if nw ~= ww or nh ~= wh then
                hl.dispatch(hl.dsp.window.resize({ x = math.floor(nw), y = math.floor(nh), exact = true, window = sel }))
            end
            hl.dispatch(hl.dsp.window.move({ x = math.floor(left + (right - left - nw) / 2),
                                             y = math.floor(top + (bottom - top - nh) / 2), window = sel }))
        end
    end
end

-- The bars come from Hyprland's hyprbars plugin, compiled into the image by the build. Hyprland
-- loads plugins after reading this file and then reads it again, so the plugin's settings are
-- only applied on that second pass, once hl.plugin.hyprbars exists. If the plugin is missing or
-- fails to load, windows simply have no bar (GTK apps draw their own, see Environment above)
-- and still move with Super+drag.
if have_hyprbars then hl.plugin.load(hyprbars_so) end
if hl.plugin.hyprbars then
    hl.config({ plugin = { hyprbars = {
        bar_height            = 34,
        bar_color             = "rgba(10111a8c)",    -- the same dark glass as GlassOS's own apps
        bar_blur              = true,
        ["col.text"]          = "rgba(ffffffd9)",
        bar_text_font         = "Inter",
        bar_text_size         = 11,
        bar_text_align        = "center",
        bar_buttons_alignment = "left",
        bar_padding           = 14,                   -- clears the rounded corner
        bar_button_padding    = 8,
        bar_part_of_window    = true,
        bar_precedence_over_border = true,
        icon_on_hover         = true,                  -- symbols show when the pointer is over them, like a Mac
        inactive_button_color = "rgba(ffffff38)",     -- grey buttons on windows that aren't focused
        on_double_click       = [[hyprctl eval 'glass_window("zoom")']],
    } } })
    -- left to right; the colours are macOS's
    for _, b in ipairs({
        { color = "rgb(ff5f57)", icon = "×", action = "close" },
        { color = "rgb(febc2e)", icon = "−", action = "minimize" },
        { color = "rgb(28c840)", icon = "+", action = "full" },
    }) do
        hl.plugin.hyprbars.add_button({
            bg_color = b.color,
            fg_color = "rgba(00000099)",
            size     = 13,
            icon     = b.icon,
            action   = string.format([[hyprctl eval 'glass_window("%s")']], b.action),
        })
    end
    -- GlassOS's own apps keep their header (it holds their tabs, search and buttons) and draw
    -- the same three buttons there, so they don't get a second bar
    hl.window_rule({
        name  = "glass-own-title-bar",
        match = { class = "^os\\.glass\\..*" },
        ["hyprbars:no_bar"] = true,
    })
end

-- Frosted glass behind the bar, dock, launcher, notifications, the top bar's drop-downs and the title
-- bar called up over a full-size window (dock.py)
for _, ns in ipairs({ "waybar", "launcher", "notifications", "glass-dock", "glass-osd", "glass-panel", "glass-titlebar" }) do
    hl.layer_rule({
        name  = "glass-blur-" .. ns,
        match = { namespace = ns },
        blur  = true,
        ignore_alpha = 0.05,
    })
end

-------------------------------------------------------------------------------
-- Keyboard shortcuts  (Super = the Windows/Command key)
--
-- Settings > Keyboard Shortcuts picks a style (GlassOS, Windows, Linux, macOS or your own) and
-- writes it to ~/.config/hypr/glass-keys.lua; without that file these are GlassOS's own keys.
-- /usr/lib/glassos/glasskeys.py has the styles. "SUPER" alone means tapping Super: it fires when
-- Super is let go, and only if no other key was pressed while it was held, so Super+E,
-- Super+drag and the rest still work. "{n}" stands for 1..9 and "{dir}" for the arrow keys.
local mod = "SUPER"

local keys = {
    search = { "SUPER" }, terminal = { "SUPER + RETURN" }, files = { "SUPER + E" }, browser = { "SUPER + B" },
    lens = { "SUPER + U" }, settings = { "SUPER + I" },
    close = { "SUPER + Q" }, fullscreen = { "SUPER + F" }, minimize = { "SUPER + M" }, float = { "SUPER + T" },
    center = { "SUPER + C" }, snap_left = { "SUPER + left" }, snap_right = { "SUPER + right" },
    focus = { "SUPER + ALT + {dir}" }, cycle = { "ALT + TAB" },
    ws_go = { "SUPER + {n}" }, ws_move = { "SUPER + SHIFT + {n}" },
    ws_next = { "SUPER + CTRL + right" }, ws_prev = { "SUPER + CTRL + left" },
    -- Shut down, restart or log out: two modifiers so it can't happen by accident, and the dialog
    -- waits 60 seconds anyway
    lock = { "SUPER + L" }, power = { "SUPER + ALT + BACKSPACE", "SUPER + ALT + DELETE" },
    shot_screen = { "Print" }, shot_area = { "SUPER + SHIFT + S" },
    notif_clear = { "SUPER + N" }, notif_restore = { "SUPER + SHIFT + N" }, shortcuts = { "SUPER + SLASH" },
}
local K = optional("glass-keys")
if type(K) == "table" and type(K.keys) == "table" then
    for id, combos in pairs(K.keys) do
        if type(combos) == "table" then keys[id] = combos end
    end
end

-- What each shortcut does. Each entry makes the thing to bind (x is the number or direction
-- for {n} and {dir} shortcuts).
local actions = {
    search     = { "Search apps",       function() return hl.dsp.exec_cmd(launcher) end },
    terminal   = { "Terminal",          function() return hl.dsp.exec_cmd(terminal) end },
    files      = { "Files",             function() return hl.dsp.exec_cmd(files) end },
    browser    = { "Web browser",       function() return hl.dsp.exec_cmd(browser) end },
    lens       = { "Glass Lens (what's using my computer)", function() return hl.dsp.exec_cmd(lens) end },
    settings   = { "Settings",          function() return hl.dsp.exec_cmd(settings) end },
    close      = { "Close window",      function() return hl.dsp.window.close() end },
    fullscreen = { "Fullscreen",        function() return hl.dsp.window.fullscreen() end },
    minimize   = { "Minimize window",   function() return function() glass_window("minimize") end end },
    float      = { "Tile / float window", function() return hl.dsp.window.float({ action = "toggle" }) end },
    center     = { "Center window",     function() return hl.dsp.window.center() end },
    snap_left  = { "Snap window to the left half",  function() return function() snap(hl.get_active_window(), "left") end end },
    snap_right = { "Snap window to the right half", function() return function() snap(hl.get_active_window(), "right") end end },
    focus      = { "Move focus",        function(d) return hl.dsp.focus({ direction = d }) end },
    cycle      = { "Next window",       function() return hl.dsp.window.cycle_next() end },
    ws_go      = { "Go to desktop",     function(n) return hl.dsp.focus({ workspace = n }) end },
    ws_move    = { "Move window to desktop", function(n) return hl.dsp.window.move({ workspace = n }) end },
    ws_next    = { "Next desktop",      function() return hl.dsp.focus({ workspace = "r+1" }) end },
    ws_prev    = { "Previous desktop",  function() return hl.dsp.focus({ workspace = "r-1" }) end },
    lock       = { "Lock screen",       function() return hl.dsp.exec_cmd("glass-lock") end },
    power      = { "Shut down, restart or log out", function() return hl.dsp.exec_cmd("glass-power") end },
    shot_screen = { "Screenshot of the whole screen", function() return hl.dsp.exec_cmd("glass-screenshot screen") end },
    shot_area  = { "Screenshot an area", function() return hl.dsp.exec_cmd("glass-screenshot area") end },
    notif_clear = { "Clear notifications", function() return hl.dsp.exec_cmd("makoctl dismiss --all") end },
    notif_restore = { "Show last notification", function() return hl.dsp.exec_cmd("makoctl restore") end },
    shortcuts  = { "Keyboard shortcuts", function() return hl.dsp.exec_cmd("glass-lens --page welcome") end },
}

-- One bad shortcut (a key name Hyprland doesn't know) is skipped instead of stopping the config
local function bind_key(combo, make, x, desc)
    pcall(function()
        if combo == "SUPER" then
            hl.bind("SUPER + SUPER_L", make(x), { release = true, description = desc })
            hl.bind("SUPER + SUPER_R", make(x), { release = true, description = desc })
        else
            hl.bind(combo, make(x), { description = desc })
        end
    end)
end

for id, a in pairs(actions) do
    for _, combo in ipairs(keys[id] or {}) do
        if type(combo) == "string" and combo ~= "" then
            if combo:find("{n}", 1, true) then
                for i = 1, 9 do bind_key((combo:gsub("{n}", tostring(i))), a[2], i, a[1]) end
            elseif combo:find("{dir}", 1, true) then
                for _, d in ipairs({ "left", "right", "up", "down" }) do bind_key((combo:gsub("{dir}", d)), a[2], d, a[1]) end
            else
                bind_key(combo, a[2], nil, a[1])
            end
        end
    end
end

-- Desktops can also be switched with Super+scroll or a 3-finger swipe
hl.bind(mod .. " + mouse_down",   hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mod .. " + mouse_up",     hl.dsp.focus({ workspace = "e-1" }))
hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })

-- Move/resize any window: hold Super and drag with left/right mouse button
hl.bind(mod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
hl.bind(mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

-- Hardware keys (volume plays your pack's "volume" sound as feedback)
hl.bind("XF86AudioRaiseVolume",  hl.dsp.exec_cmd("glass-volume up"),   { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume",  hl.dsp.exec_cmd("glass-volume down"), { locked = true, repeating = true })
hl.bind("XF86AudioMute",         hl.dsp.exec_cmd("glass-volume mute"), { locked = true })
hl.bind("XF86AudioMicMute",      hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"), { locked = true })
hl.bind("XF86MonBrightnessUp",   hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"), { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"), { locked = true, repeating = true })
hl.bind("XF86AudioNext",  hl.dsp.exec_cmd("playerctl next"),       { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay",  hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev",  hl.dsp.exec_cmd("playerctl previous"),   { locked = true })

-------------------------------------------------------------------------------
-- Your own additions: create ~/.config/hypr/custom.lua and it will be loaded last.
optional("custom")
