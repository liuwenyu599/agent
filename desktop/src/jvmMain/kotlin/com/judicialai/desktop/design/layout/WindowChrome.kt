package com.judicialai.desktop.design.layout

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.hoverable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.input.pointer.PointerInputScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.WindowScope
import java.awt.Color
import java.awt.Cursor
import java.awt.Dimension
import java.awt.Frame
import java.awt.Point
import java.awt.Rectangle
import java.awt.event.WindowStateListener
import kotlin.math.roundToInt

/**
 * 无边框窗口外壳（undecorated + transparent）
 *
 * 系统原生标题栏（那条白边 + 系统渲染的标题文字）去掉后，窗口能力必须由界面自己补回来：
 * - [WindowChrome]：透明底 + 圆角裁剪（最大化时改直角）；
 * - 拖动：[Modifier.dragWindow]，顶部拖拽带 + Header 空白处；
 * - 缩放：四边 / 四角自绘热区，仅在非最大化时生效；
 * - 控制按钮：[WindowChromeActions] 经 [LocalWindowChrome] 下发到 AppShell 的 Header
 *   （AppHeader 深处拿不到 WindowScope）。
 */
data class WindowChromeActions(
    /** 最小化窗口 */
    val minimize: () -> Unit = {},
    /** 最大化 / 还原切换 */
    val toggleMaximize: () -> Unit = {},
    /** 关闭窗口（行为与 onCloseRequest 完全一致） */
    val close: () -> Unit = {},
    /** 当前是否最大化（决定圆角与最大化按钮图标） */
    val maximized: Boolean = false,
    /** 宿主 AWT 窗口，供拖拽使用；为 null 表示当前不在无边框窗口内 */
    val window: java.awt.Window? = null,
)

/** 无边框窗口能力；非无边框环境（如预览）取到 null，界面自动隐藏窗口控制按钮。 */
val LocalWindowChrome = staticCompositionLocalOf<WindowChromeActions?> { null }

/** 窗口圆角 */
val WINDOW_CORNER_RADIUS: Dp = 12.dp

/** 顶部透明拖拽带高度：给圆角留出呼吸空间，同时提供拖动 / 双击最大化入口 */
val WINDOW_DRAG_STRIP_HEIGHT: Dp = 10.dp

/** 窗口最小尺寸（与 rememberWindowState 的 1280×800 匹配） */
private val WINDOW_MIN_SIZE: Dimension = Dimension(1100, 700)

/** 边缘缩放热区厚度 */
private val RESIZE_EDGE: Dp = 6.dp

/** 四角缩放热区边长（角优先于边） */
private val RESIZE_CORNER: Dp = 14.dp

/** 双击判定：两次按下间隔上限 */
private const val DOUBLE_TAP_TIMEOUT_MS = 300L

/** 双击判定：两次按下位置偏差上限（px） */
private const val DOUBLE_TAP_SLOP = 20f

/**
 * 窗口外框：透明底 + 圆角裁剪 + 顶部拖拽带 + 边缘缩放热区。
 *
 * @param maximized 是否最大化（最大化时圆角为 0，且禁用所有缩放热区）
 * @param cornerRadius 正常状态下的窗口圆角
 * @param dragStripHeight 顶部透明拖拽带高度
 * @param minimumSize 窗口最小尺寸（缩放时用于夹取下限）
 * @param onToggleMaximize 顶部拖拽带双击时的最大化 / 还原逻辑；传 null 则不启用双击
 */
@Composable
fun WindowScope.WindowChrome(
    maximized: Boolean = false,
    cornerRadius: Dp = WINDOW_CORNER_RADIUS,
    dragStripHeight: Dp = WINDOW_DRAG_STRIP_HEIGHT,
    minimumSize: Dimension = WINDOW_MIN_SIZE,
    onToggleMaximize: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    // 透明窗口必须把 AWT 窗口底色也设为全透明，否则圆角外会露出系统白底（即「白边」）
    LaunchedEffect(Unit) { window.background = Color(0, 0, 0, 0) }
    LaunchedEffect(minimumSize) { window.minimumSize = minimumSize }

    val shape: Shape = if (maximized) RectangleShape else RoundedCornerShape(cornerRadius)
    Box(Modifier.fillMaxSize().clip(shape)) {
        content()
        // 顶部透明拖拽带：不占视觉，替代系统标题栏拖动；双击 = 最大化 / 还原
        Box(
            Modifier.align(Alignment.TopCenter)
                .fillMaxWidth()
                .height(dragStripHeight)
                .dragWindow(window, onDoubleTap = onToggleMaximize)
        )
        // 无边框窗口没有系统缩放热区，这里自绘；最大化时不启用
        if (!maximized) {
            WindowResizeHandles(window = window, minSize = minimumSize)
        }
    }
}

/**
 * 构造当前窗口的 [WindowChromeActions]（必须在 WindowScope 内调用）。
 *
 * @param maximized 当前最大化状态
 * @param close 关闭逻辑，要求与 Window 的 onCloseRequest 完全一致
 */
@Composable
fun WindowScope.windowChromeActions(
    maximized: Boolean,
    close: () -> Unit,
): WindowChromeActions {
    val host = window
    return WindowChromeActions(
        minimize = { (host as? Frame)?.extendedState = Frame.ICONIFIED },
        toggleMaximize = {
            val frame = host as? Frame
            if (frame != null) {
                frame.extendedState = if (frame.isMaximized) Frame.NORMAL else Frame.MAXIMIZED_BOTH
            }
        },
        close = close,
        maximized = maximized,
        window = host,
    )
}

/** 当前 AWT 窗口是否处于最大化状态 */
private val Frame.isMaximized: Boolean
    get() = (extendedState and Frame.MAXIMIZED_BOTH) == Frame.MAXIMIZED_BOTH

/**
 * 监听窗口最大化 / 还原，把状态回调出去（用于切换圆角与最大化按钮图标）。
 * 必须在 WindowScope 内调用。
 */
@Composable
fun WindowScope.trackWindowMaximized(onChange: (Boolean) -> Unit) {
    val host = window
    DisposableEffect(host) {
        val listener = WindowStateListener {
            onChange((host as? Frame)?.isMaximized ?: false)
        }
        host.addWindowStateListener(listener)
        onChange((host as? Frame)?.isMaximized ?: false)
        onDispose { host.removeWindowStateListener(listener) }
    }
}

/**
 * 让任意区域（如 Header 空白处、顶部拖拽带）可以拖动无边框窗口。
 *
 * 不依赖 WindowScope，因此 AppHeader 这类深层 composable 也能使用。
 * 传入 null（不在无边框窗口内）时该 modifier 为空操作。
 *
 * @param onDoubleTap 双击回调（顶部拖拽带用来切换最大化）；传 null 则不监听双击
 */
fun Modifier.dragWindow(
    window: java.awt.Window?,
    onDoubleTap: (() -> Unit)? = null,
): Modifier {
    if (window == null) return this
    return this
        .pointerInput(window) {
            // Compose 用逻辑像素，AWT window.location 用物理像素；高 DPI 屏必须换算
            val scale = window.graphicsConfiguration?.defaultTransform?.scaleX ?: 1.0
            var origin = Point(0, 0)
            var dx = 0f
            var dy = 0f
            detectDragGestures(
                onDragStart = {
                    origin = window.location
                    dx = 0f
                    dy = 0f
                },
                onDragEnd = { dx = 0f; dy = 0f },
                onDragCancel = { dx = 0f; dy = 0f },
                onDrag = { _, dragAmount ->
                    dx += dragAmount.x
                    dy += dragAmount.y
                    window.location = Point(
                        origin.x + (dx * scale).roundToInt(),
                        origin.y + (dy * scale).roundToInt(),
                    )
                },
            )
        }
        .then(
            if (onDoubleTap != null) {
                Modifier.pointerInput(window, onDoubleTap) { detectDoubleTap(onDoubleTap) }
            } else {
                Modifier
            }
        )
}

/**
 * 双击识别：连续两次按下（间隔 ≤ [DOUBLE_TAP_TIMEOUT_MS]、位移 ≤ [DOUBLE_TAP_SLOP]）触发。
 *
 * 只读取事件、不消费，因此可以与同一区域的拖动手势共存。
 */
private suspend fun PointerInputScope.detectDoubleTap(onDoubleTap: () -> Unit) {
    var lastDownTime = 0L
    var lastDownPosition: Offset? = null
    awaitEachGesture {
        val down = awaitFirstDown(requireUnconsumed = false)
        val previous = lastDownPosition
        if (
            previous != null &&
            down.uptimeMillis - lastDownTime <= DOUBLE_TAP_TIMEOUT_MS &&
            (down.position - previous).getDistance() <= DOUBLE_TAP_SLOP
        ) {
            lastDownTime = 0L
            lastDownPosition = null
            onDoubleTap()
        } else {
            lastDownTime = down.uptimeMillis
            lastDownPosition = down.position
        }
        // 等本次按下抬起，避免同一次按下被重复计数
        waitForUpOrCancellation()
    }
}

/** 自绘缩放热区：四边 + 四角（角后画 → 命中优先） */
@Composable
private fun BoxScope.WindowResizeHandles(
    window: java.awt.Window,
    minSize: Dimension,
) {
    ResizeHandle(
        Modifier.align(Alignment.CenterStart).fillMaxHeight().width(RESIZE_EDGE),
        window, ResizeEdge.LEFT, minSize,
    )
    ResizeHandle(
        Modifier.align(Alignment.CenterEnd).fillMaxHeight().width(RESIZE_EDGE),
        window, ResizeEdge.RIGHT, minSize,
    )
    ResizeHandle(
        Modifier.align(Alignment.TopCenter).fillMaxWidth().height(RESIZE_EDGE),
        window, ResizeEdge.TOP, minSize,
    )
    ResizeHandle(
        Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(RESIZE_EDGE),
        window, ResizeEdge.BOTTOM, minSize,
    )
    ResizeHandle(
        Modifier.align(Alignment.TopStart).size(RESIZE_CORNER),
        window, ResizeEdge.TOP_LEFT, minSize,
    )
    ResizeHandle(
        Modifier.align(Alignment.TopEnd).size(RESIZE_CORNER),
        window, ResizeEdge.TOP_RIGHT, minSize,
    )
    ResizeHandle(
        Modifier.align(Alignment.BottomStart).size(RESIZE_CORNER),
        window, ResizeEdge.BOTTOM_LEFT, minSize,
    )
    ResizeHandle(
        Modifier.align(Alignment.BottomEnd).size(RESIZE_CORNER),
        window, ResizeEdge.BOTTOM_RIGHT, minSize,
    )
}

/** 单个缩放热区：透明、只占最外圈，悬停时切换鼠标指针 */
@Composable
private fun BoxScope.ResizeHandle(
    modifier: Modifier,
    window: java.awt.Window,
    edge: ResizeEdge,
    minSize: Dimension,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    LaunchedEffect(hovered, edge, window) {
        window.cursor = if (hovered) {
            Cursor.getPredefinedCursor(edge.cursorId)
        } else {
            Cursor.getDefaultCursor()
        }
    }
    Box(
        modifier
            .hoverable(interactionSource = interaction)
            .resizeWindowEdge(window = window, edge = edge, minSize = minSize)
    )
}

/** 拖动热区改变窗口 bounds */
private fun Modifier.resizeWindowEdge(
    window: java.awt.Window,
    edge: ResizeEdge,
    minSize: Dimension,
): Modifier = this.pointerInput(window, edge, minSize) {
    // 与拖动同理：逻辑像素 → 物理像素
    val scale = window.graphicsConfiguration?.defaultTransform?.scaleX ?: 1.0
    var start: Rectangle? = null
    var dx = 0f
    var dy = 0f
    detectDragGestures(
        onDragStart = {
            start = window.bounds
            dx = 0f
            dy = 0f
            window.cursor = Cursor.getPredefinedCursor(edge.cursorId)
        },
        onDragEnd = { window.cursor = Cursor.getDefaultCursor() },
        onDragCancel = { window.cursor = Cursor.getDefaultCursor() },
        onDrag = { _, dragAmount ->
            val bounds = start ?: return@detectDragGestures
            dx += dragAmount.x
            dy += dragAmount.y
            val next = resizeBounds(edge, bounds, minSize, dx, dy, scale)
            window.setBounds(next.x, next.y, next.width, next.height)
        },
    )
}

/** 按热区方向计算新 bounds，并用 [minSize] 夹取下限，避免把窗口拖成 0 宽 / 0 高 */
private fun resizeBounds(
    edge: ResizeEdge,
    start: Rectangle,
    minSize: Dimension,
    dx: Float,
    dy: Float,
    scale: Double,
): Rectangle {
    val sdx = (dx * scale).roundToInt()
    val sdy = (dy * scale).roundToInt()
    var x = start.x
    var y = start.y
    var width = start.width
    var height = start.height

    if (edge.resizeLeft) {
        val nextWidth = (start.width - sdx).coerceAtLeast(minSize.width)
        x = start.x + (start.width - nextWidth)
        width = nextWidth
    } else if (edge.resizeRight) {
        width = (start.width + sdx).coerceAtLeast(minSize.width)
    }

    if (edge.resizeTop) {
        val nextHeight = (start.height - sdy).coerceAtLeast(minSize.height)
        y = start.y + (start.height - nextHeight)
        height = nextHeight
    } else if (edge.resizeBottom) {
        height = (start.height + sdy).coerceAtLeast(minSize.height)
    }

    return Rectangle(x, y, width, height)
}

/** 缩放方向（决定鼠标指针与 bounds 计算方式） */
private enum class ResizeEdge(
    val cursorId: Int,
    val resizeLeft: Boolean = false,
    val resizeRight: Boolean = false,
    val resizeTop: Boolean = false,
    val resizeBottom: Boolean = false,
) {
    LEFT(Cursor.W_RESIZE_CURSOR, resizeLeft = true),
    RIGHT(Cursor.E_RESIZE_CURSOR, resizeRight = true),
    TOP(Cursor.N_RESIZE_CURSOR, resizeTop = true),
    BOTTOM(Cursor.S_RESIZE_CURSOR, resizeBottom = true),
    TOP_LEFT(Cursor.NW_RESIZE_CURSOR, resizeLeft = true, resizeTop = true),
    TOP_RIGHT(Cursor.NE_RESIZE_CURSOR, resizeRight = true, resizeTop = true),
    BOTTOM_LEFT(Cursor.SW_RESIZE_CURSOR, resizeLeft = true, resizeBottom = true),
    BOTTOM_RIGHT(Cursor.SE_RESIZE_CURSOR, resizeRight = true, resizeBottom = true),
}
