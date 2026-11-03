// @filter 形狀塗色
// @description 內部用：內建形狀節點的填充／外框接了圖片時，把圖片貼進形狀的範圍（遮罩）裡，疊在形狀的其他部分下面（填充）或上面（外框）
// @source 圖片
// @input base "形狀"
// @input mask "範圍"
// @param over bool false "疊在上面"

vec4 effect(vec2 uv) {
    vec4 below = input_base(uv);
    vec4 paint = src(uv) * input_mask(uv).a;
    return over ? paint + below * (1.0 - paint.a) : below + paint * (1.0 - below.a);
}
