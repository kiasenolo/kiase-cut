// @filter 漩渦
// @category 扭曲
// @description 畫面繞著中心扭轉
// @param angle float 180 -1080 1080 "角度"
// @param radius float 0.5 0.05 2 "範圍"
// @param center vec2 0.5,0.5 0 1 "中心"
vec4 effect(vec2 uv) {
    vec2 asp = vec2(resolution.x / resolution.y, 1.0);
    vec2 d = (uv - center) * asp;
    float f = 1.0 - length(d) / radius;
    if (f <= 0.0) return src(uv);
    float a = radians(angle) * f * f;
    d = mat2(cos(a), sin(a), -sin(a), cos(a)) * d;
    return src(center + d / asp);
}
