// @filter 毛玻璃
// @category 模糊
// @description 像隔著磨砂玻璃看：每一點都被打散到附近
// @param amount float 8 0 50 "散開距離"
// @param softness float 0.5 0 1 "柔化"
vec4 effect(vec2 uv) {
    if (amount <= 0.0) return src(uv);
    vec2 p = floor(uv * resolution);                 // the same scatter every frame
    int n = 1 + int(softness * 15.0);
    vec4 sum = vec4(0.0);
    for (int i = 0; i < 16; i++) {
        if (i >= n) break;
        float a = rand(p + vec2(float(i) * 7.13, 1.7)) * 6.2831853;
        float r = sqrt(rand(p + vec2(float(i) * 3.71, 9.2))) * amount;
        sum += src(uv + vec2(cos(a), sin(a)) * r / resolution);
    }
    return sum / float(n);
}
