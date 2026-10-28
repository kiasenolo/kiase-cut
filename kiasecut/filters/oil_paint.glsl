// @filter 油畫
// @category 風格
// @description 細節抹平成一塊塊筆觸，邊緣仍然清楚（Kuwahara 濾鏡）
// @param size float 10 1 60 "筆觸大小"
vec4 effect(vec2 uv) {
    // of the four squares that touch this pixel, the one whose colour varies least gives its
    // average; each square is read on a 6 x 6 grid, size canvas px across
    vec2 step_ = vec2(size / 5.0) / resolution;
    vec4 best = src(uv);
    float least = 1e9;
    for (int q = 0; q < 4; q++) {
        vec2 dir = vec2(q == 1 || q == 3 ? 1.0 : -1.0, q >= 2 ? 1.0 : -1.0);
        vec4 sum = vec4(0.0);
        vec3 sq = vec3(0.0);
        for (int j = 0; j < 6; j++) {
            for (int i = 0; i < 6; i++) {
                vec4 s = src(uv + dir * vec2(float(i), float(j)) * step_);
                sum += s;
                sq += s.rgb * s.rgb;
            }
        }
        vec4 m = sum / 36.0;
        vec3 var = sq / 36.0 - m.rgb * m.rgb;
        float v = var.r + var.g + var.b;
        if (v < least) {
            least = v;
            best = m;
        }
    }
    return best;
}
