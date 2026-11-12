// @filter 陰影
// @description 內部用：每個片段「畫面」裡的陰影參數，把片段自己的樣子模糊、位移、上色後放在它後面
// @passes 5
// @param on bool true "啟用"
// @param color color #000000 "顏色"
// @param opacity float 0.5 0 1 "不透明度"
// @param x float 6 -500 500 "X"
// @param y float 6 -500 500 "Y"
// @param blur float 8 0 200 "模糊"
// @param spread float 0 0 64 "擴張"

// Passes: 0-1 the shape grown by spread (the distance to the nearest solid pixel - alpha above 4% - along rows, then
// columns, as Inner Shadow does: exact and round for any size); 2-3 its alpha blurred, rows then columns (a Gaussian of
// sigma = blur / 3 cut at blur, 32 taps a side, so any blur costs the same); 4 the blurred shape, moved, in colour, under the
// picture. Sizes are px of a 1080 high canvas.
#define MAXD 64.0

float gauss_a(vec2 uv, vec2 dir, float r) {
    if (r < 0.25) return src(uv).r;
    float sum = 0.0, total = 0.0;
    for (int i = -32; i <= 32; i++) {
        float f = float(i) / 32.0;
        float w = exp(-4.5 * f * f);
        sum += src(uv + dir * f * r / resolution).r * w;
        total += w;
    }
    return sum / total;
}

float solid(vec2 p) { return (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) ? 0.0 : step(0.04, original(p).a); }

vec4 effect(vec2 uv) {
    float k = resolution.y / 1080.0;
    float r = max(blur, 0.0) * k;
    float g = min(max(spread, 0.0) * k, MAXD);
    float stp = max(1.0, resolution.x / float(textureSize(source, 0).x));     // canvas px between two pixels of the picture worked on
    if (pass_index == 0) {
        if (g < 0.5) return vec4(original(uv).a);
        float best = MAXD;
        for (int i = -64; i <= 64; i++) {
            float d = float(i) * stp;
            if (abs(d) > g + 1.0) continue;
            if (solid(uv + vec2(d / resolution.x, 0.0)) >= 0.5) best = min(best, abs(d));
        }
        return vec4(best / MAXD);
    }
    if (pass_index == 1) {
        if (g < 0.5) return src(uv);
        float best = MAXD * MAXD;
        for (int i = -64; i <= 64; i++) {
            float d = float(i) * stp;
            if (abs(d) > g + 1.0) continue;
            float f = src(uv + vec2(0.0, d / resolution.y)).r * MAXD;
            best = min(best, f * f + d * d);
        }
        return vec4(max(clamp(g + 1.0 - sqrt(best), 0.0, 1.0), original(uv).a));
    }
    if (pass_index == 2) return vec4(gauss_a(uv, vec2(1.0, 0.0), r));
    if (pass_index == 3) return vec4(gauss_a(uv, vec2(0.0, 1.0), r));
    vec4 pic = original(uv);
    if (!on) return pic;
    vec2 p = uv - vec2(x, y) * k / resolution;
    float m = (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) ? 0.0 : src(p).r;
    float a = clamp(color.a * opacity * m, 0.0, 1.0);
    return vec4(pic.rgb + color.rgb * a * (1.0 - pic.a), pic.a + a * (1.0 - pic.a));
}
