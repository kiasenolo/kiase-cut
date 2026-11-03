// @filter 顏色
// @category 輸入
// @description 節點用：照 Blender 的「RGB」節點：一個常數顏色，整張圖都是這個顏色。接到別的節點的圖片輸入（像「混合」）當顏色用
// @param color color #ffffff "顏色"

vec4 effect(vec2 uv) {
    return vec4(color.rgb * color.a, color.a);
}
