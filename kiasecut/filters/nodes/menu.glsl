// @filter 選單
// @category 輸入
// @description 節點用：照 Blender 的「選單」節點（Menu）：選一個選項，輸出它的編號（從 0 開始，整張圖都是這個數字）。接到選單切換的選單（或任何數字輸入）就能用一個選單控制它。這裡的選項是固定的 8 個（選項 1 到 選項 8），名字照選單切換的選項順序對應
// @param choice menu "選項 1" "選項 1|選項 2|選項 3|選項 4|選項 5|選項 6|選項 7|選項 8" "選單"

vec4 effect(vec2 uv) {
    return vec4(vec3(float(choice)), 1.0);
}
