// @filter 分離 XYZ
// @category 向量
// @description 節點用：照 Blender 的「分離 XYZ」：圖像的紅綠藍當成向量 (X, Y, Z)，各拆成一張灰階圖，各有一個輸出
// @output x "X"
// @output y "Y"
// @output z "Z"

vec4 effect(vec2 uv) {
    vec3 v = unpremultiply(src(uv)).rgb;
    float f = output_index == 0 ? v.x : output_index == 1 ? v.y : v.z;
    return vec4(vec3(f), 1.0);
}
