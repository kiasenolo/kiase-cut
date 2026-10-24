// @filter RGB 色差
// @category 風格
// @description 紅、藍通道往相反方向錯開
// @param amount float 10 0 100 "距離"
// @param angle float 0 0 360 "角度"
vec4 effect(vec2 uv) {
    float a = radians(angle);
    vec2 o = vec2(cos(a), sin(a)) * amount * scale / resolution;
    vec4 r = src(uv + o);
    vec4 g = src(uv);
    vec4 b = src(uv - o);
    return vec4(r.r, g.g, b.b, max(g.a, max(r.a, b.a)));
}
