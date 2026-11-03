// @filter 擴張／侵蝕
// @category 濾鏡
// @description 節點用：照 Blender 的「擴張／侵蝕」節點（Dilate/Erode）：遮罩（圖進來是黑白的明度）往外擴張（大小為正）或往內侵蝕（大小為負），輸出是黑白的圖。步驟：每次一個像素的方形視窗取最大／最小；閾值：遮罩 > 0.5 算有，用到最近的邊的距離，距離小於大小的算有，再用「衰減大小」做一段由 1 到 0 的線性過渡；距離：圓形視窗取最大／最小；羽化：加上高斯權重和衰減曲線的柔和邊緣（曲線選平滑、球形、平方根、反平方、銳利、線性）。大小是 0 就原樣輸出
// @source "遮罩"
// @passes 16
// @levels 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
// @skip 2-14 kind != 閾值
// @param size int 0 -1000 1000 "大小"
// @param kind menu 步驟 "步驟|閾值|距離|羽化" "類型"
// @param falloff_size float 0 0 1000 "衰減大小"
// @param falloff menu 平滑 "平滑|球形|平方根|反平方|銳利|線性" "衰減"
// @enable falloff_size kind == 閾值
// @enable falloff kind == 羽化

// Blender 5.2 (compositor_morphological_step / _distance / _distance_threshold / _distance_feather.glsl) rewritten for KiaseCut;
// checked against its results on masks (steps, distance, threshold with its falloff, feather with every falloff curve, and erode).
// Differences: Distance uses a square window of the same width on the two sides (Blender's loop reads the other side's end,
// so it cuts a tall picture short); a big size reads every few pixels (at most about 96 per side, 48 in the round window), the way the other big filters do.
// The threshold's nearest edge is found by jump flooding as Blender's does: pass 0 marks, passes 1 - 14 jump 8192, 4096 ... 1 pixels,
// the last pass makes the picture. (x, y) of the nearest masked pixel is in red, green, of the nearest unmasked one in blue, alpha;
// -1 where there is none.

const int CAP = 96;
float bright(vec4 c) { return dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)); }
bool outside(vec2 p) { return p.x < 0.0 || p.y < 0.0 || p.x >= resolution.x || p.y >= resolution.y; }

// pass 0, steps / feather / distance: the mask's value, the pass after reads it; and one of the two axes of steps / feather
float line_max(vec2 pix, vec2 dir, bool take_bright) {
    int r = abs(size);
    float stride = max(1.0, ceil(float(r) / float(CAP)));
    bool dilate = size > 0;
    float v = dilate ? -1e30 : 1e30;
    for (int j = -CAP; j <= CAP; j++) {
        float i = float(j) * stride;
        if (abs(i) > float(r)) continue;
        vec2 p = pix + dir * i;
        if (outside(p)) continue;
        vec4 c = src((p + 0.5) / resolution);
        float x = take_bright ? bright(c) : c.r;
        v = dilate ? max(v, x) : min(v, x);
    }
    return v;
}

float falloff_of(float x) {
    switch (falloff) {
    case 0: return 3.0 * x * x - 2.0 * x * x * x;
    case 1: return sqrt(max(2.0 * x - x * x, 0.0));
    case 2: return sqrt(x);
    case 3: return x * (2.0 - x);
    case 4: return x * x;
    }
    return x;
}

float fn(float x) { return size < 0 ? 1.0 - x : x; }

float line_feather(vec2 pix, vec2 dir, bool take_bright) {
    float s = float(abs(size));
    float stride = max(1.0, ceil(s / float(CAP)));
    float norm = 1.0;                                          // (the sum of the Gaussian over -s .. s, the middle one counted once)
    for (int j = 1; j <= CAP; j++) {
        float i = float(j) * stride;
        if (i > s) break;
        norm += 2.0 * stride * exp(-4.5 * i * i / (s * s));
    }
    vec4 c0 = src((pix + 0.5) / resolution);
    float centre = fn(take_bright ? bright(c0) : c0.r);
    float acc = centre / norm;
    float limit = centre, limit_falloff = 1.0;
    for (int j = 1; j <= CAP; j++) {
        float i = float(j) * stride;
        if (i >= s) break;
        float w = exp(-4.5 * i * i / (s * s)) / norm * stride;
        float f = falloff_of(1.0 - i / s);
        for (int k = -1; k < 2; k += 2) {
            vec2 p = clamp(pix + dir * (float(k) * i), vec2(0.0), resolution - 1.0);          // (the nearest pixel at the edge)
            vec4 c = src((p + 0.5) / resolution);
            float x = fn(take_bright ? bright(c) : c.r);
            acc += x * w;
            if (x * f > limit) {
                limit = x * f;
                limit_falloff = f;
            }
        }
    }
    return fn(mix(acc, limit, limit_falloff));
}

float disc(vec2 pix) {
    int r = abs(size);
    float stride = max(1.0, ceil(float(r) / float(CAP / 4)));
    bool dilate = size > 0;
    float v = dilate ? -1e30 : 1e30;
    for (int j = -CAP / 4; j <= CAP / 4; j++) {
        float y = float(j) * stride;
        if (abs(y) > float(r)) continue;
        for (int k = -CAP / 4; k <= CAP / 4; k++) {
            float x = float(k) * stride;
            if (x * x + y * y > float(r * r)) continue;
            vec2 p = pix + vec2(x, y);
            if (outside(p)) continue;
            float c = src((p + 0.5) / resolution).r;
            v = dilate ? max(v, c) : min(v, c);
        }
    }
    return v;
}

// jump flooding: the nearest seed of a pixel among those of the pixels step away
vec2 nearer(vec2 pix, vec2 best, vec2 cand) {
    if (cand.x < 0.0) return best;
    if (best.x < 0.0) return cand;
    return dot(cand - pix, cand - pix) < dot(best - pix, best - pix) ? cand : best;
}

vec4 flood(vec2 pix, float step_size) {
    vec4 s = src((pix + 0.5) / resolution);
    vec2 a = s.xy, b = s.zw;
    for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
            vec2 p = pix + vec2(float(i), float(j)) * step_size;
            if (outside(p)) continue;
            vec4 t = src((p + 0.5) / resolution);
            a = nearer(pix, a, t.xy);
            b = nearer(pix, b, t.zw);
        }
    }
    return vec4(a, b);
}

vec4 grey(float v) { return vec4(vec3(v), 1.0); }

vec4 effect(vec2 uv) {
    vec2 pix = floor(uv * resolution);
    if (pass_index == 15) {                                    // the picture
        if (size == 0) return grey(bright(original(uv)));
        if (kind != 1) return grey(src(uv).r);
        vec4 s = src(uv);
        bool masked = bright(original(uv)) > 0.5;
        vec2 other = masked ? s.zw : s.xy;
        float d = other.x < 0.0 ? 1e6 : distance(pix, other);
        float signed_d = masked ? d : -d;
        return grey(clamp((signed_d + float(size)) / max(falloff_size, 1e-5), 0.0, 1.0));
    }
    if (size == 0) return vec4(0.0);
    if (kind == 1) {                                           // threshold: seeds, then the jumps
        if (pass_index == 0) {
            bool masked = bright(src(uv)) > 0.5;
            return vec4(masked ? pix : vec2(-1.0), masked ? vec2(-1.0) : pix);
        }
        float step_size = exp2(float(14 - pass_index));
        return step_size >= 2.0 * max(resolution.x, resolution.y) ? src(uv) : flood(pix, step_size);
    }
    if (pass_index == 0) {
        if (kind == 0) return vec4(vec3(line_max(pix, vec2(1.0, 0.0), true)), 1.0);
        if (kind == 3) return vec4(vec3(line_feather(pix, vec2(1.0, 0.0), true)), 1.0);
        return grey(bright(src(uv)));
    }
    if (kind == 0) return vec4(vec3(line_max(pix, vec2(0.0, 1.0), false)), 1.0);
    if (kind == 3) return vec4(vec3(line_feather(pix, vec2(0.0, 1.0), false)), 1.0);
    return grey(disc(pix));
}
