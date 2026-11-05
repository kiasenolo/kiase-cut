// @filter 模糊
// @category 模糊
// @description 照 Blender 的「模糊」節點（Blur）：大小是像素（X、Y 可以不同），類型有平坦、帳篷、二次、三次、高斯、快速高斯、Catrom、Mitch，權重和 Blender 的一樣；預設分離（先橫向、再縱向），關掉分離就是圓形（橢圓）的核；延伸邊界讓畫面外算透明，不然邊緣的顏色會延伸出去。線性光：在線性光裡運算（Blender 合成器是線性的），關著就直接糊顏色的數值
// @passes 2
// @param radius float 10 0 1000 "大小 X"
// @param radius_y float 10 0 1000 "大小 Y"
// @param link_xy bool true "XY 相同"
// @param kind menu 高斯 "平坦|帳篷|二次|三次|高斯|快速高斯|Catrom|Mitch" "類型"
// @param extend bool false "延伸邊界"
// @param separable bool true "分離"
// @param linear_light bool false "線性光"
// @enable radius_y !link_xy

// Reimplementation of Blender's Blur compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

// Weights as Blender's (RE_filter_value, used by the Blur node of the compositor): the tap at distance i from the
// centre weighs kern(i / size), taps out to ceil(size) on each side, the weights normalised to a sum of 1. Not
// separable: the weight of a tap is kern of its distance in size units, sqrt((x / size_x)^2 + (y / size_y)^2), over the box
// of ceil(size_x) x ceil(size_y). Checked against Blender 5.2.
// A very big size is read every few pixels.

const float GAUSSFAC = 1.6;
const int MAX_TAPS = 96;           // taps on each side along a line
const int MAX_TAPS_2D = 24;        // ... and along each side of the box when it is not separable

float quad_(float x) { x = abs(x); return x < 0.5 ? 0.75 - x * x : x < 1.5 ? 0.5 * (x - 1.5) * (x - 1.5) : 0.0; }
float cubic_(float x) {
    x = abs(x);
    float x2 = x * x;
    return x < 1.0 ? 0.5 * x * x2 - x2 + 2.0 / 3.0 : x < 2.0 ? pow(2.0 - x, 3.0) / 6.0 : 0.0;
}
float catrom_(float x) {
    x = abs(x);
    float x2 = x * x;
    return x < 1.0 ? 1.5 * x2 * x - 2.5 * x2 + 1.0 : x < 2.0 ? -0.5 * x2 * x + 2.5 * x2 - 4.0 * x + 2.0 : 0.0;
}
float mitchell_(float x) {
    const float b = 1.0 / 3.0, c = 1.0 / 3.0;
    x = abs(x);
    if (x < 1.0) return (6.0 - 2.0 * b) / 6.0 + x * x * ((-18.0 + 12.0 * b + 6.0 * c) / 6.0 + x * (12.0 - 9.0 * b - 6.0 * c) / 6.0);
    if (x < 2.0) return (8.0 * b + 24.0 * c) / 6.0 + x * ((-12.0 * b - 48.0 * c) / 6.0 + x * ((6.0 * b + 30.0 * c) / 6.0 + x * (-b - 6.0 * c) / 6.0));
    return 0.0;
}

float kern(float t) {
    t = abs(t);
    switch (kind) {
    case 0: return t <= 1.0 ? 1.0 : 0.0;
    case 1: return max(1.0 - t, 0.0);
    case 2: return quad_(t * GAUSSFAC);
    case 3: return cubic_(t * GAUSSFAC);
    case 4:
    case 5: return exp(-4.5 * t * t);
    case 6: return catrom_(t * GAUSSFAC);
    }
    return mitchell_(t * GAUSSFAC);
}

vec3 to_lin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c)); }
vec3 to_enc(vec3 c) { c = max(c, 0.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c)); }

// (premultiplied) the picture at uv: nothing outside it when the bounds are extended
vec4 tap(vec2 uv) {
    if (extend && (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0)) return vec4(0.0);
    vec4 c = src(uv);
    if (linear_light && c.a > 0.0) c.rgb = to_lin(c.rgb / c.a) * c.a;
    return c;
}

vec4 result(vec4 s) {
    float a = clamp(s.a, 0.0, 1.0);
    vec3 rgb = max(s.rgb, 0.0);                  // (not held to the alpha or to 1: a node's picture can be brighter)
    if (linear_light && a > 0.0) rgb = to_enc(rgb / a) * a;
    return vec4(rgb, a);
}

// taps to read on a side of a line size long (ceil(size); a fast Gaussian reaches further), and the step between them
int taps(float size, out float stride) {
    float n = ceil(size * (kind == 5 ? 1.5 : 1.0));
    stride = max(1.0, ceil(n / float(MAX_TAPS)));
    return int(n);
}

vec4 line(vec2 uv, vec2 dir, float size) {
    if (size <= 0.0) return src(uv);
    float stride;
    int n = taps(size, stride);
    vec2 d = dir / resolution;
    float w0 = kern(0.0);
    vec4 acc = tap(uv) * w0;
    float total = w0;
    for (int j = 1; j <= MAX_TAPS; j++) {
        float i = float(j) * stride;
        if (i > float(n)) break;
        float w = kern(i / size);
        if (w == 0.0) continue;
        acc += w * (tap(uv + d * i) + tap(uv - d * i));
        total += 2.0 * w;
    }
    return result(acc / total);
}

vec4 box(vec2 uv, float sx, float sy) {
    if (sx <= 0.0 && sy <= 0.0) return src(uv);
    float strx, stry;
    int nx = taps(sx, strx), ny = taps(sy, stry);
    strx = max(strx, ceil(float(nx) / float(MAX_TAPS_2D)));
    stry = max(stry, ceil(float(ny) / float(MAX_TAPS_2D)));
    vec4 acc = vec4(0.0);
    float total = 0.0;
    for (int j = -MAX_TAPS_2D; j <= MAX_TAPS_2D; j++) {
        float y = float(j) * stry;
        if (abs(y) > float(ny)) continue;
        float ty = sy > 0.0 ? y / sy : 0.0;
        for (int k = -MAX_TAPS_2D; k <= MAX_TAPS_2D; k++) {
            float x = float(k) * strx;
            if (abs(x) > float(nx)) continue;
            float tx = sx > 0.0 ? x / sx : 0.0;
            float w = kern(sqrt(tx * tx + ty * ty));
            if (w == 0.0) continue;
            acc += w * tap(uv + vec2(x, y) / resolution);
            total += w;
        }
    }
    return result(acc / total);
}

vec4 effect(vec2 uv) {
    float sx = max(radius, 0.0);
    float sy = link_xy ? sx : max(radius_y, 0.0);
    if (!separable) return pass_index == 0 ? src(uv) : box(uv, sx, sy);        // (all in the last pass)
    return pass_index == 0 ? line(uv, vec2(1.0, 0.0), sx) : line(uv, vec2(0.0, 1.0), sy);
}
