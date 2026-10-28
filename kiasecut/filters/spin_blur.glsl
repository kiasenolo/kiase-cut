// @filter 旋轉模糊
// @category 模糊
// @description 繞著中心轉動的模糊，像轉動中的輪子或鏡頭在旋轉
// @param angle float 10 0 180 "角度"
// @param center vec2 0.5,0.5 0 1 "中心"
vec4 effect(vec2 uv) {
    if (angle <= 0.0) return src(uv);
    vec2 asp = vec2(resolution.x / resolution.y, 1.0);
    vec2 d = (uv - center) * asp;
    float j = rand(uv * resolution);                 // each pixel's samples a little apart: grain, not bands
    vec4 sum = vec4(0.0);
    for (int i = 0; i < 64; i++) {
        float a = radians(angle) * ((float(i) + j) / 64.0 - 0.5);
        sum += src(center + mat2(cos(a), sin(a), -sin(a), cos(a)) * d / asp);
    }
    return sum / 64.0;
}
