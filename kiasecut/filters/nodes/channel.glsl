// @filter 分離通道
// @category 節點
// @description 節點用：取圖像的一個通道（紅、綠、藍、透明度或明度），輸出成不透明的灰階圖
// @param channel menu 紅 "紅|綠|藍|透明度|明度" "通道"

vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    float v = channel == 0 ? c.r : channel == 1 ? c.g : channel == 2 ? c.b : channel == 3 ? c.a
            : dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)) * c.a;
    return vec4(vec3(v), 1.0);
}
