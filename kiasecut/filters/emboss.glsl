// @filter 浮雕
// @category 風格
// @description 畫面像壓在金屬或石頭上的浮雕，邊緣一邊亮一邊暗
// @param strength float 2 0 8 "強度"
// @param angle float 135 0 360 "光的方向"
// @param distance float 1.5 0.5 8 "厚度"
// @param keep_color bool false "保留顏色"
vec4 effect(vec2 uv) {
    float a = radians(angle);
    vec2 o = vec2(cos(a), -sin(a)) * distance / resolution;
    vec4 c = src(uv);
    vec3 w = vec3(0.299, 0.587, 0.114);
    float relief = (dot(src(uv - o).rgb, w) - dot(src(uv + o).rgb, w)) * strength;
    if (keep_color) return vec4(clamp(c.rgb + relief * c.a, 0.0, c.a), c.a);
    return vec4(vec3(clamp(0.5 + relief, 0.0, 1.0)) * c.a, c.a);
}
