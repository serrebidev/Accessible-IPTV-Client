"""The private MPV helper, embedded so frozen builds need no extra data file.

MPV explicitly recommends register_idle for combining property changes.
Read a complete snapshot there instead of joining independently delivered
IPC properties in Python. Observations may still coalesce: this is current
displayed text, not a lossless subtitle-file extraction API.
"""

SCRIPT = r'''
local mp = require 'mp'
local utils = require 'mp.utils'
local dirty, force = true, true
local epoch, serial = 0, 0
local previous = nil
local active = not mp.get_property_native('idle-active', true)
local seeking = false

local function changed() dirty = true end
local function boundary()
    epoch = epoch + 1
    dirty = true
end

for _, name in ipairs({'sub-text', 'sub-start', 'sub-end', 'sid',
                        'pause', 'paused-for-cache', 'track-list', 'sub-visibility', 'sub-delay'}) do
    mp.observe_property(name, 'native', changed)
end
mp.register_event('start-file', function()
    active, seeking = false, true
    boundary()
end)
mp.register_event('file-loaded', function() active = true; boundary() end)
mp.register_event('end-file', function() active = false; boundary() end)
mp.register_event('seek', function() seeking = true; boundary() end)
mp.register_event('playback-restart', function() seeking = false; dirty = true end)
mp.register_script_message('iptvclient-subtitle-request', function()
    dirty, force = true, true
end)

mp.register_idle(function()
    if not dirty then return end
    dirty = false
    local sid = mp.get_property_native('sid', false)
    local text = active and not seeking and mp.get_property_native('sub-text', '') or ''
    local codec = ''
    local image = false
    for _, track in ipairs(mp.get_property_native('track-list', {})) do
        if track.type == 'sub' and track.id == sid then
            codec = track.codec or ''
            image = track.image == true or codec == 'hdmv_pgs_subtitle'
                or codec == 'dvd_subtitle' or codec == 'dvb_subtitle'
        end
    end
    -- sid=no and visibility=no must not resurrect text from a disabled track.
    if sid == false or not mp.get_property_native('sub-visibility', true) then
        text = ''
    end
    local snapshot = {
        protocol = 1, epoch = epoch, active = active and not seeking, track = tostring(sid),
        -- Network buffering can suspend a live programme without pause=yes.
        -- Use the same output-purge/review policy as an explicit pause.
        text = text, paused = mp.get_property_native('pause', false)
            or mp.get_property_native('paused-for-cache', false),
        start = mp.get_property_native('sub-start'),
        finish = mp.get_property_native('sub-end'),
        codec = codec, image = image,
    }
    local signature = utils.format_json(snapshot)
    if force or signature ~= previous then
        force = false
        previous = signature
        serial = serial + 1
        snapshot.serial = serial
        snapshot.position = mp.get_property_native('time-pos')
        -- format_json returns (text, error). Passing it as the last argument
        -- would expand both return values into commandv.
        local payload = utils.format_json(snapshot)
        if payload then
            mp.commandv('script-message', 'iptvclient-subtitle-snapshot', payload)
        end
    end
end)
'''
