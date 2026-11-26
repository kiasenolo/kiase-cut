// @filter 撒點紋理
// @category 紋理
// @description 節點用：在畫面上隨機撒點（星星、灰塵、雪）。分佈：白雜訊（完全隨機，會有擠成一團和空掉的地方）、藍雜訊（點和點保持距離，分佈均勻又看不出格子）。「比例」是撒點格子的密度，「密度」是留下多少點（1 時平均每 2 格 1 點）。半徑以格子為單位。向量沒接線就用影像座標（長邊 -1 到 1，Y 向上）。輸出「數值」（點是亮的、其他是 0）、「顏色」（每個點一個隨機顏色）和「ID」（每個點一個 0 到 1 的隨機值）
// @source "向量"
// @input in_scale "比例" tex_scale
// @input in_density "密度" density
// @input in_radius "半徑" radius
// @output value "數值"
// @output color "顏色"
// @output point_id "ID"
// @data blue_noise
// @param distribution menu 藍雜訊 "白雜訊|藍雜訊" "分佈"
// @param tex_scale float 20 -1000000 1000000 "比例"
// @param density float 0.5 0 1 "密度"
// @param radius float 0.15 0 1 "半徑"
// @param size_random float 0 0 1 "大小隨機"
// @param bright_random float 0 0 1 "亮度隨機"
// @param softness float 0 0 1 "邊緣柔和"
// @param seed int 0 0 1000000 "Seed"
// @param offset vec2 0,0 -1000000 1000000 "偏移"
// @bake distribution
// @socket in - vector
// @socket out value float
// @socket out color color
// @socket out point_id float

// SPDX-FileCopyrightText: KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec3 uniform_coords(vec2 uv) {          // (as the other texture nodes' unlinked Vector)
    vec2 R = resolution, p = vec2(uv.x, 1.0 - uv.y) * R, q = floor(p) + 0.5;
    if (all(lessThan(abs(p - q), vec2(0.002)))) p = q;
    return vec3((p - R / 2.0) / max(R.x, R.y) * 2.0, 0.0);
}
vec3 vector_in(vec2 uv) { return has_src() ? unpremultiply(src(uv)).rgb : uniform_coords(uv); }
float num(bool linked, vec4 c, float field) { return linked ? dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)) * (c.a > 0.0 ? 1.0 : 0.0) : field; }

// three numbers 0 - 1 of a cell (pcg3d)
vec3 cell_hash(ivec2 c, int s) {
    uvec3 v = uvec3(ivec3(c, s)) * 1664525u + 1013904223u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    return vec3(v >> 8u) / 16777216.0;
}

float best, best_id;
vec3 best_color;
// the point at `at` (cells), in cell `c`, number k of it: how much of this pixel (at p) it covers
void point_at(vec2 p, vec2 at, ivec2 c, int k, float r0, float px) {
    vec3 own = cell_hash(c, seed * 8 + k + 1048576);           // (its size, brightness and ID)
    float r = r0 * (1.0 - size_random * own.x);
    if (r <= 0.0) return;
    float edge = max(r * softness, px);
    float cover = clamp((r + px * 0.5 - distance(p, at)) / edge, 0.0, 1.0) * min(1.0, 2.0 * r / px);   // (smaller than a pixel: fainter)
    float v = cover * (1.0 - bright_random * own.y);
    if (v > best) {
        best = v;
        best_id = own.z;
        best_color = cell_hash(c, seed * 8 + k + 2097152);
    }
}

vec4 effect(vec2 uv) {
    float sc = num(has_input_in_scale(), input_in_scale(uv), tex_scale);
    float dn = clamp(num(has_input_in_density(), input_in_density(uv), density), 0.0, 1.0);
    float r0 = clamp(num(has_input_in_radius(), input_in_radius(uv), radius), 0.0, 1.0);
    vec2 p = vector_in(uv).xy * sc + offset;
    float px = max(abs(sc) * 2.0 / max(pass_px.x, pass_px.y), 1e-6);       // a drawn pixel, in cells
    ivec2 base = ivec2(floor(p));
    best = 0.0;
    best_id = 0.0;
    best_color = vec3(0.0);
    // another seed moves the blue noise tile and may turn it over its diagonal
    vec3 turn = seed == 0 ? vec3(0.0) : cell_hash(ivec2(seed, 0), 77);
    ivec2 shift = ivec2(turn.xy * 64.0);
    bool diagonal = turn.z > 0.5;
    for (int y = -1; y <= 1; y++)                              // (a point reaches one cell at most)
        for (int x = -1; x <= 1; x++) {
            ivec2 c = base + ivec2(x, y);
            if (distribution == 1) {
                ivec2 t = ((diagonal ? c.yx : c) + shift) & 63;
                vec4 d = texelFetch(data_blue_noise_, t, 0);
                if (d.a > 0.5 && d.b < dn)
                    point_at(p, vec2(c) + (diagonal ? d.gr : d.rg), c, 0, r0, px);
            } else {
                for (int k = 0; k < 4; k++) {                  // (up to four to a cell, each there on its own chance)
                    vec3 h = cell_hash(c, seed * 8 + k);
                    if (h.z < dn * 0.125)
                        point_at(p, vec2(c) + h.xy, c, k, r0, px);
                }
            }
        }
    if (output_index == 0) return vec4(vec3(best), 1.0);
    if (output_index == 1) return vec4(best_color * best, 1.0);
    return vec4(vec3(best > 0.0 ? best_id : 0.0), 1.0);
}
