// @filter 陰影
// @description 內部用：每個片段「畫面」裡的陰影參數，把片段自己的樣子模糊、位移、上色後放在它後面
// @passes 3
// @param on bool true "啟用"
// @param color color #000000 "顏色"
// @param opacity float 0.5 0 1 "不透明度"
// @param x float 6 -500 500 "X"
// @param y float 6 -500 500 "Y"
// @param blur float 8 0 200 "模糊"

// Passes: 0-1 the picture's alpha blurred, rows then columns (a Gaussian of sigma = blur / 3 cut at blur, 32 taps a side, so any
// blur costs the same); 2 the blurred shape, moved, in colour, under the picture. Sizes are px of a 1080 high canvas.
float gauss_a(vec2 uv, vec2 dir, float r, bool first) {
    if (r < 0.25) return first ? src(uv).a : src(uv).r;
    float sum = 0.0, total = 0.0;
    for (int i = -32; i <= 32; i++) {
        float f = float(i) / 32.0;
        float w = exp(-4.5 * f * f);
        vec4 s = src(uv + dir * f * r / resolution);
        sum += (first ? s.a : s.r) * w;
        total += w;
    }
    return sum / total;
}

vec4 effect(vec2 uv) {
    float k = resolution.y / 1080.0;
    float r = max(blur, 0.0) * k;
    if (pass_index == 0) return vec4(gauss_a(uv, vec2(1.0, 0.0), r, true));
    if (pass_index == 1) return vec4(gauss_a(uv, vec2(0.0, 1.0), r, false));
    vec4 pic = original(uv);
    if (!on) return pic;
    vec2 p = uv - vec2(x, y) * k / resolution;
    float m = (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) ? 0.0 : src(p).r;
    float a = clamp(color.a * opacity * m, 0.0, 1.0);
    return vec4(pic.rgb + color.rgb * a * (1.0 - pic.a), pic.a + a * (1.0 - pic.a));
}
