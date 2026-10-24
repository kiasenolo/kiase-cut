// @filter 半色調
// @category 風格
// @description 印刷網點：越暗的地方點越大
// @param size float 10 2 80 "網點大小"
// @param angle float 45 0 90 "角度"
// @param colored bool true "彩色網點"
// @param paper color #ffffff "紙的顏色"
vec4 effect(vec2 uv) {
    float s = size * scale;
    float a = radians(angle);
    mat2 rot = mat2(cos(a), sin(a), -sin(a), cos(a));
    vec2 p = rot * (uv * resolution);
    vec2 cell = (floor(p / s) + 0.5) * s;
    vec4 cc = unpremultiply(src(transpose(rot) * cell / resolution));
    float l = dot(cc.rgb, vec3(0.299, 0.587, 0.114));
    float rad = sqrt(1.0 - l) * s * 0.7071;
    float ink = 1.0 - smoothstep(rad - 1.0, rad + 1.0, length(p - cell));
    vec3 rgb = mix(paper.rgb, colored ? cc.rgb : vec3(0.0), ink);
    return premultiply(vec4(rgb, src(uv).a));
}
