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
-- Older (GTK 3) apps like Files and Text Editor draw their own title bar, so every window has
-- one to drag and close
hl.env("GTK_CSD", "1")

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
            -- a thin specular rim, brighter on the top-left like light hitting glass
            active_border   = { colors = { "rgba(ffffff70)", "rgba(ffffff18)" }, angle = 135 },
            inactive_border = { colors = { "rgba(ffffff30)", "rgba(ffffff0a)" }, angle = 135 },
        },
        resize_on_border = true,
        extend_border_grab_area = 12,
        hover_icon_on_border = true,
        layout = "dwindle",
        snap = { enabled = true, window_gap = 10, monitor_gap = 10 },
    },

    decoration = {
        rounding       = 16,
        rounding_power = 3.0,      -- superellipse corners
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

        blur = {
            enabled   = true,
            size      = M.light and 4 or pick(S.frost_size, 5),     -- Settings > Appearance > Frost
            passes    = M.light and 1 or pick(S.frost_passes, 2),
            noise     = 0.012,
            contrast  = 1.0,
            brightness = 0.66,    -- darkens what shows through, so white text stays readable over white pages
            vibrancy  = 0.5,      -- keeps the wallpaper's colour in the glass
            vibrancy_darkness = 0.25,
            popups    = true,
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

local function keep_on_screen(w)
    if not w or not w.floating or w.fullscreen ~= 0 or not w.monitor then return end
    local m = w.monitor
    local mw, mh = m.width / m.scale, m.height / m.scale
    if m.transform % 2 == 1 then mw, mh = mh, mw end
    local left, top, right, bottom = m.x, m.y, m.x + mw, m.y + mh
    for _, l in ipairs(hl.get_layers()) do
        if l.namespace == "waybar" and l.monitor and l.monitor.id == m.id and l.y < m.y + mh / 2 then
            top = math.max(top, l.y + l.h + 6)
        end
    end
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

hl.bind("mouse:272", function() keep_on_screen(hl.get_active_window()) end,
        { release = true, non_consuming = true, ignore_mods = true })

-- Make full size (the maximize button, or double-clicking a title bar) works like full screen
-- on a Mac: the window covers the whole screen and the top bar and dock get out of the way. The
-- app still thinks it's only maximized, so it keeps its title bar and the button to shrink back.
hl.on("window.fullscreen", function(w)
    w = w or hl.get_active_window()
    if w and w.fullscreen == 1 then
        hl.dispatch(hl.dsp.window.fullscreen_state({ internal = 2, client = 1, window = "address:" .. w.address }))
    end
end)

-- Frosted glass behind the bar, dock, launcher and notifications
for _, ns in ipairs({ "waybar", "launcher", "notifications", "glass-dock", "glass-osd" }) do
    hl.layer_rule({
        name  = "glass-blur-" .. ns,
        match = { namespace = ns },
        blur  = true,
        ignore_alpha = 0.05,
    })
end

-------------------------------------------------------------------------------
-- Keyboard shortcuts  (Super = the Windows/Command key)
local mod = "SUPER"

-- Tap Super on its own to search apps. It fires when Super is let go, and only if no other key
-- was pressed while it was held, so Super+E, Super+drag and the rest still work as before.
hl.bind(mod .. " + SUPER_L", hl.dsp.exec_cmd(launcher), { release = true, description = "Search apps" })
hl.bind(mod .. " + SUPER_R", hl.dsp.exec_cmd(launcher), { release = true, description = "Search apps" })
hl.bind(mod .. " + RETURN", hl.dsp.exec_cmd(terminal),          { description = "Terminal" })
hl.bind(mod .. " + E",      hl.dsp.exec_cmd(files),             { description = "Files" })
hl.bind(mod .. " + B",      hl.dsp.exec_cmd(browser),           { description = "Web browser" })
hl.bind(mod .. " + U",      hl.dsp.exec_cmd(lens),              { description = "Glass Lens (what's using my computer)" })
hl.bind(mod .. " + I",      hl.dsp.exec_cmd(settings),          { description = "Settings" })
hl.bind(mod .. " + Q",      hl.dsp.window.close(),              { description = "Close window" })
hl.bind(mod .. " + F",      hl.dsp.window.fullscreen(),         { description = "Fullscreen" })
hl.bind(mod .. " + T",      hl.dsp.window.float({ action = "toggle" }), { description = "Tile / float window" })
hl.bind(mod .. " + C",      hl.dsp.window.center(),             { description = "Center window" })
hl.bind(mod .. " + L",      hl.dsp.exec_cmd("glass-lock"),      { description = "Lock screen" })
-- Shut down, restart or log out: Super+Option+Delete on a Mac keyboard, Super+Alt+Backspace on a
-- PC. Two modifiers so it can't happen by accident, and the dialog waits 60 seconds anyway.
hl.bind(mod .. " + ALT + BACKSPACE", hl.dsp.exec_cmd("glass-power"), { description = "Shut down, restart or log out" })
hl.bind(mod .. " + ALT + DELETE",    hl.dsp.exec_cmd("glass-power"), { description = "Shut down, restart or log out" })
hl.bind(mod .. " + N",      hl.dsp.exec_cmd("makoctl dismiss --all"), { description = "Clear notifications" })
hl.bind(mod .. " + SHIFT + N", hl.dsp.exec_cmd("makoctl restore"),     { description = "Show last notification" })
hl.bind(mod .. " + SLASH",  hl.dsp.exec_cmd("glass-lens --page welcome"), { description = "Keyboard shortcuts" })

-- Screenshots
hl.bind("Print",               hl.dsp.exec_cmd("glass-screenshot screen"))
hl.bind(mod .. " + SHIFT + S", hl.dsp.exec_cmd("glass-screenshot area"), { description = "Screenshot an area" })

-- Focus / move
hl.bind(mod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mod .. " + down",  hl.dsp.focus({ direction = "down" }))
hl.bind("ALT + TAB",       hl.dsp.window.cycle_next())

-- Workspaces ("desktops"): Super+1..9, Super+Ctrl+arrows, or 3-finger swipe
for i = 1, 9 do
    hl.bind(mod .. " + " .. i,             hl.dsp.focus({ workspace = i }))
    hl.bind(mod .. " + SHIFT + " .. i,     hl.dsp.window.move({ workspace = i }))
end
hl.bind(mod .. " + CTRL + right", hl.dsp.focus({ workspace = "r+1" }))
hl.bind(mod .. " + CTRL + left",  hl.dsp.focus({ workspace = "r-1" }))
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
