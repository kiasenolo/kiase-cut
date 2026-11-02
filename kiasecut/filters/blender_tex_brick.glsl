// @filter [Blender] Brick Texture
// @category Blender
// @description Blender 的磚塊紋理：一排排錯開的磚，磚縫可以調粗細和柔邊
// @param color1 color #cc6644 "磚色 1"
// @param color2 color #884433 "磚色 2"
// @param mortar_color color #202020 "磚縫顏色"
// @param mortar_size float 0.02 0 0.125 "磚縫大小"
// @param mortar_smooth float 0.1 0 1 "磚縫柔邊"
// @param bias float 0 -1 1 "偏向"
// @param brick_width float 0.5 0.01 100 "磚寬"
// @param row_height float 0.25 0.01 100 "列高"
// @param offset_amount float 0.5 0 1 "錯位"
// @param offset_freq int 2 1 99 "錯位間隔"
// @param squash float 1 0 99 "壓縮"
// @param squash_freq int 2 1 99 "壓縮間隔"
// @param tex_scale float 5 0.001 1000 "比例"
// @param offset vec2 0,0 -1000 1000 "位置"
// @param amount float 1 0 1 "強度"

// Source: the Brick Texture shader node of Blender (source/blender/gpu/shaders/material/
// gpu_shader_material_tex_*.glsl), rewritten by hand for KiaseCut - the same pattern and parameters,
// the cell/hash randomness is not bit-identical with Blender. The coordinates are Blender's image
// coordinates (the long side -1..1, y up) times 比例. Where the clip is transparent it stays so;
// 強度 mixes the pattern over the clip's own colours.
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec3 tex_co(vec2 uv) {
    vec2 R = resolution;
    return vec3(vec2(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0) * R / max(R.x, R.y) * tex_scale + offset, 0.0);
}
vec3 pcg3(uvec3 v) {
    v = v * 1664525u + 1013904223u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    return vec3(v) * (1.0 / 4294967295.0);
}
vec3 hash2(vec2 c) { return pcg3(uvec3(uint(int(c.x) + 65536), uint(int(c.y) + 65536), 7u)); }
vec4 finish(vec2 uv, vec3 rgb) {
    vec4 c = src(uv);
    vec3 base = c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
    return vec4(mix(base, rgb, amount) * c.a, c.a);
}

vec4 effect(vec2 uv) {
    vec3 p = tex_co(uv);
    float rownum = floor(p.y / row_height);
    float bw = (squash_freq > 0 && int(mod(rownum, float(squash_freq))) == 0) ? brick_width * squash : brick_width;
    float off = (offset_freq > 0 && int(mod(rownum, float(offset_freq))) == 0) ? bw * offset_amount : 0.0;
    float bricknum = floor((p.x + off) / bw);
    float x = (p.x + off) - bw * bricknum;
    float y = p.y - row_height * rownum;
    float tint = clamp(hash2(vec2(rownum, bricknum)).x + bias, 0.0, 1.0);
    float min_dist = min(min(x, y), min(bw - x, row_height - y));
    float mortar;
    if (min_dist >= mortar_size) mortar = 0.0;
    else if (mortar_smooth == 0.0) mortar = 1.0;
    else mortar = smoothstep(0.0, mortar_smooth, 1.0 - min_dist / mortar_size);
    vec3 brick = mix(color1.rgb, color2.rgb, tint);
    return finish(uv, mix(brick, mortar_color.rgb, mortar));
}
