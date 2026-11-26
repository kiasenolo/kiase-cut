// @filter Voronoi 裂紋
// @category 紋理
// @description 節點用：Voronoi 的 F2 − F1（第二近的點的距離減最近的距離）：細胞交界是 0、越往裡越亮，可以做裂紋、龜甲、邊緣發光。每格一個抖動的點，隨機性 0 是整齊的格子。向量沒接線就用影像座標（長邊 -1 到 1，Y 向上）。輸出「數值」（F2 − F1）、「顏色」（每個細胞一個隨機顏色）和「ID」（每個細胞一個 0 到 1 的隨機值）
// @source "向量"
// @input in_scale "比例" tex_scale
// @input in_random "隨機性" randomness
// @output value "數值"
// @output color "顏色"
// @output cell_id "ID"
// @param metric menu 歐幾里得 "歐幾里得|曼哈頓|切比雪夫" "距離"
// @param tex_scale float 5 -1000000 1000000 "比例"
// @param randomness float 1 0 1 "隨機性"
// @param seed int 0 0 1000000 "Seed"
// @param offset vec2 0,0 -1000000 1000000 "偏移"
// @bake metric
// @socket in - vector
// @socket out value float
// @socket out color color
// @socket out cell_id float

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
float how_far(vec2 d) {
    if (metric == 1) return abs(d.x) + abs(d.y);
    if (metric == 2) return max(abs(d.x), abs(d.y));
    return length(d);
}

vec4 effect(vec2 uv) {
    float sc = num(has_input_in_scale(), input_in_scale(uv), tex_scale);
    float rnd = clamp(num(has_input_in_random(), input_in_random(uv), randomness), 0.0, 1.0);
    vec2 p = vector_in(uv).xy * sc + offset;
    ivec2 base = ivec2(floor(p));
    vec2 f = p - vec2(base);
    float f1 = 1e9, f2 = 1e9;
    ivec2 nearest = base;
    for (int y = -2; y <= 2; y++)                              // (5 x 5: the second nearest point can be two cells away)
        for (int x = -2; x <= 2; x++) {
            vec2 h = cell_hash(base + ivec2(x, y), seed).xy;
            float d = how_far(vec2(x, y) + 0.5 + (h - 0.5) * rnd - f);
            if (d < f1) { f2 = f1; f1 = d; nearest = base + ivec2(x, y); }
            else if (d < f2) f2 = d;
        }
    if (output_index == 0) return vec4(vec3(f2 - f1), 1.0);
    vec3 c = cell_hash(nearest, seed + 7919);                  // (not the numbers that placed the point)
    return vec4(output_index == 1 ? c : vec3(c.x), 1.0);
}
