package cc.devault.delight1

import android.content.ClipboardManager
import android.content.Context
import android.view.ContextThemeWrapper
import android.view.LayoutInflater
import android.view.Menu
import android.view.MenuInflater
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.PopupMenu
import android.widget.Toast
import androidx.core.content.ContextCompat
import androidx.databinding.DataBindingUtil
import androidx.databinding.ViewDataBinding
import androidx.fragment.app.DialogFragment
import androidx.fragment.app.Fragment
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.LiveData
import androidx.lifecycle.MediatorLiveData
import androidx.recyclerview.widget.DividerItemDecoration
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import java.util.*
import kotlin.reflect.KClass


val libBitcoin by lazy { libMod("bitcoin") }
val libUtil by lazy { libMod("util") }


// See Settings.kt
var unitName = ""
var unitPlaces = 0


fun toSatoshis(s: String, places: Int = unitPlaces) : Long {
    val unit = Math.pow(10.0, places.toDouble())
    try {
        return Math.round(s.toDouble() * unit)
    } catch (e: NumberFormatException) {
        throw ToastException(R.string.Invalid_amount)
    }
}

// We use Locale.US to be consistent with lib/exchange_rate.py, which is also locale-insensitive.
@JvmOverloads  // For data binding call in address_list.xml.
fun formatSatoshis(amount: Long, places: Int = unitPlaces): String {
    val unit = Math.pow(10.0, places.toDouble())
    var result = "%.${places}f".format(Locale.US, amount / unit).trimEnd('0')
    if (result.endsWith(".")) {
        result += "0"
    }
    return result
}

fun formatSatoshisAndUnit(amount: Long): String {
    return "${formatSatoshis(amount)} $unitName"
}


fun showDialog(target: Fragment, frag: DialogFragment) {
    showDialog(target.activity!!, frag, target)
}

fun showDialog(activity: FragmentActivity, frag: DialogFragment, target: Fragment? = null) {
    val fm = activity.supportFragmentManager
    val tag = frag::class.java.name
    if (fm.findFragmentByTag(tag) == null) {
        if (target != null) {
            frag.setTargetFragment(target, 0)
        }
        frag.showNow(fm, tag)
    }
}


fun <T: DialogFragment> findDialog(activity: FragmentActivity, fragClass: KClass<T>) : T? {
    val tag = fragClass.java.name
    val frag = activity.supportFragmentManager.findFragmentByTag(tag)
    if (frag == null) {
        return null
    } else if (frag::class != fragClass) {
        throw ClassCastException(
            "Expected ${fragClass.java.name}, got ${frag::class.java.name}")
    } else {
        @Suppress("UNCHECKED_CAST")
        return frag as T?
    }
}


fun copyToClipboard(text: CharSequence, what: Int? = null) {
    @Suppress("DEPRECATION")
    (getSystemService(ClipboardManager::class)).text = text
    val message = if (what == null) app.getString(R.string.text_copied)
                  else app.getString(R.string._s_copied, app.getString(what))
    toast(message, Toast.LENGTH_SHORT)
}


fun <T: Any> getSystemService(kcls: KClass<T>): T {
    return ContextCompat.getSystemService(app, kcls.java)!!
}


fun setupVerticalList(rv: RecyclerView) {
    rv.layoutManager = LinearLayoutManager(rv.context)

    // Dialog theme has listDivider set to null, so use the base app theme instead.
    rv.addItemDecoration(
        DividerItemDecoration(ContextThemeWrapper(rv.context, R.style.AppTheme),
                                                           DividerItemDecoration.VERTICAL))
}


// The RecyclerView ListAdapter gives some nice animations when the list changes, but I found
// the diff process was too slow when comparing long transaction lists. However, we do emulate
// its API here in case we try it again in the future.
open class BoundAdapter<T: Any>(val layoutId: Int)
    : RecyclerView.Adapter<BoundViewHolder<T>>() {

    var list: List<T> = listOf()

    fun submitList(newList: List<T>?) {
        list = newList ?: listOf()
        notifyDataSetChanged()
    }

    override fun getItemCount() =
        list.size

    fun getItem(position: Int) =
        list.get(position)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): BoundViewHolder<T> {
        val layoutInflater = LayoutInflater.from(parent.context)
        val binding = DataBindingUtil.inflate<ViewDataBinding>(
            layoutInflater, layoutId, parent, false)
        return BoundViewHolder(binding)
    }

    override fun onBindViewHolder(holder: BoundViewHolder<T>, position: Int) {
        holder.item = getItem(position)
        holder.binding.setVariable(BR.model, holder.item)
        holder.binding.executePendingBindings()
    }
}

class BoundViewHolder<T: Any>(val binding: ViewDataBinding)
    : RecyclerView.ViewHolder(binding.root) {

    lateinit var item: T
}


class MenuAdapter(context: Context, val menu: Menu)
    : ArrayAdapter<String>(context, android.R.layout.simple_spinner_item, menuToList(menu)) {
    init {
        if (context === app) {
            // This resulted in white-on-white text on older API levels (e.g. 18).
            throw IllegalArgumentException(
                "Can't use application context: theme will not be applied to views")
        }
        setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
    }

    constructor(context: Context, menuId: Int)
        : this(context, inflateMenu(menuId))

    override fun getItemId(position: Int): Long {
        return menu.getItem(position).itemId.toLong()
    }
}

fun inflateMenu(menuId: Int) : Menu {
    val menu = PopupMenu(app, null).menu
    MenuInflater(app).inflate(menuId, menu)
    return menu
}

private fun menuToList(menu: Menu): List<String> {
    val result = ArrayList<String>()
    for (i in 0 until menu.size()) {
        result.add(menu.getItem(i).title.toString())
    }
    return result
}


// When the TriggerLiveData becomes active, it will call its observers at most once, no matter
// how many sources it has.
class TriggerLiveData : MediatorLiveData<Unit>() {
    enum class State {
        NORMAL, ACTIVATING, ACTIVE
    }
    private var state = State.NORMAL

    // Using postValue would also call observers at most once, but some observers need to be
    // called synchronously. For example, postponing the setup of a RecyclerView adapter would
    // cause the view to lose its scroll position on rotation.
    fun addSource(source: LiveData<*>) {
        addSource(source, {
            if (state != State.ACTIVE) {
                setValue(Unit)
                if (state == State.ACTIVATING) {
                    state = State.ACTIVE
                }
            }
        })
    }

    override fun onActive() {
        state = State.ACTIVATING
        super.onActive()
        state = State.NORMAL
    }
}