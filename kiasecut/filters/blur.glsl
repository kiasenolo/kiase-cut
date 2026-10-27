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
    if (stride == 1.0) {
        // every pixel out to r: the centre, then each pair of neighbours (d, d + 1) in one
        // read between them, where the texture's linear filtering mixes them by their weights
        // - the same sum with half the reads
        int n = int(r);
        sum = src(uv);
        total = 1.0;
        for (int i = 1; i <= 48; i += 2) {
            if (i > n) break;
            float d1 = float(i), d2 = float(i + 1);
            float w1 = exp(-0.5 * d1 * d1 / (sigma * sigma));
            float w2 = i + 1 <= n ? exp(-0.5 * d2 * d2 / (sigma * sigma)) : 0.0;
            float w = w1 + w2;
            float d = (d1 * w1 + d2 * w2) / w;
            sum += (src(uv + px * d) + src(uv - px * d)) * w;
            total += 2.0 * w;
        }
        return sum / total;
    }
    for (int i = -48; i <= 48; i++) {
        float d = float(i) * stride;
        if (abs(d) > r) continue;
        float w = exp(-0.5 * d * d / (sigma * sigma));
        sum += src(uv + px * d) * w;
        total += w;
    }
    return sum / total;
}
