// @filter 放射模糊
// @category 模糊
// @description 從中心往外衝的模糊
// @param amount float 0.2 0 1 "強度"
// @param center vec2 0.5,0.5 0 1 "中心"
vec4 effect(vec2 uv) {
    if (amount <= 0.0) return src(uv);
    vec4 sum = vec4(0.0);
    for (int i = 0; i < 48; i++) {
        float f = float(i) / 47.0;
        sum += src(center + (uv - center) * (1.0 - amount * f));
    }
    return sum / 48.0;
}
