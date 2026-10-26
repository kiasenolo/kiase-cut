// @filter 模糊
// @category 模糊
// @description 高斯模糊（兩次繪製：先橫向、再縱向）
// @passes 2
// @param radius float 10 0 150 "半徑"
vec4 effect(vec2 uv) {
    float r = radius;
    if (r < 0.5) return src(uv);
    vec2 dir = pass_index == 0 ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
    vec2 px = dir / resolution;
    float sigma = r / 2.0;
    float stride = max(1.0, r / 48.0);          // very large radii skip pixels
    vec4 sum = vec4(0.0);
    float total = 0.0;
    for (int i = -48; i <= 48; i++) {
        float d = float(i) * stride;
        if (abs(d) > r) continue;
        float w = exp(-0.5 * d * d / (sigma * sigma));
        sum += src(uv + px * d) * w;
        total += w;
    }
    return sum / total;
}
