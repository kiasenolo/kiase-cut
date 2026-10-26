// @filter 方向模糊
// @category 模糊
// @description 往一個方向拉開的動態模糊
// @param amount float 40 0 400 "距離"
// @param angle float 0 0 360 "角度"
vec4 effect(vec2 uv) {
    float r = amount;
    if (r < 0.5) return src(uv);
    vec2 dir = vec2(cos(radians(angle)), sin(radians(angle))) * r / resolution;
    vec4 sum = vec4(0.0);
    for (int i = 0; i < 48; i++) {
        sum += src(uv + dir * (float(i) / 47.0 - 0.5));
    }
    return sum / 48.0;
}
