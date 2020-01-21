package cc.devault.delight1

import android.app.Dialog
import android.content.Context
import android.os.Bundle
import android.text.InputType
import android.util.AttributeSet
import android.view.Menu
import android.view.MenuInflater
import android.view.MenuItem
import android.view.View
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.observe
import androidx.preference.EditTextPreference
import androidx.preference.EditTextPreferenceDialogFragmentCompat
import com.chaquo.python.PyException
import com.chaquo.python.PyObject
import kotlinx.android.synthetic.main.network.*


private val PROTOCOL_SUFFIX = ":s"

val libNetwork by lazy { libMod("network") }


fun initNetwork() {
    settings.getBoolean("auto_connect").observeForever { autoConnect ->
        daemonModel.network.callAttr("set_whitelist_only", autoConnect)  // See #1636.
        updateNetwork()
    }
    settings.getString("server").observeForever { updateNetwork() }
}


private fun updateNetwork() {
    daemonModel.network.callAttr("load_parameters")
}


class NetworkActivity : AppCompatActivity(R.layout.network) {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setupVerticalList(rvIfaces)
        rvIfaces.adapter = IfacesAdapter(this)
        daemonUpdate.observe(this, { refresh() })
    }

    fun refresh() {
        val ifaceLock = daemonModel.network.get("interface_lock")!!
        ifaceLock.callAttr("acquire")
        val ifaces = ArrayList(daemonModel.network.get("interfaces")!!.asMap().values)
        ifaces.sortBy { it.get("server").toString() }
        ifaceLock.callAttr("release")

        var status = getString(R.string.connected_to, ifaces.size)
        val isSplit = daemonModel.network.callAttr("get_blockchains").asMap().size > 1
        if (isSplit) {
            val curChain = daemonModel.network.callAttr("blockchain")
            status += "\n" + getString(R.string.chain_split,
                                       curChain.callAttr("get_base_height").toInt())
        }
        tvStatus.text = status

        val serverIface = daemonModel.network.get("interface")
        if (serverIface != null) {
            tvServer.text = serverIface.callAttr("format_address").toString()
        } else {
            tvServer.setText(R.string.not_connected)
        }
        (rvIfaces.adapter as IfacesAdapter).submitList(ifaces.map { IfaceModel(it, isSplit) })
    }
}


class IfacesAdapter(val activity: FragmentActivity)
    : BoundAdapter<IfaceModel>(R.layout.iface) {

    override fun onBindViewHolder(holder: BoundViewHolder<IfaceModel>, position: Int) {
        super.onBindViewHolder(holder, position)
        holder.itemView.setOnClickListener {
            showDialog(activity, IfaceDialog(holder.item.address))
        }
    }
}

class IfaceModel(iface: PyObject, isSplit: Boolean) {
    val address = iface.callAttr("format_address").toString()
    val blockchain = iface.get("blockchain")
    val height = blockchain?.callAttr("height").toString()
    val split = if (isSplit && blockchain != null)
                    blockchain.callAttr("format_base").toString()
                else ""
}


class IfaceDialog() : MenuDialog() {
    constructor(address: String) : this() {
        arguments = Bundle().apply { putString("address", address) }
    }
    val address by lazy { arguments!!.getString("address")!! }

    override fun onBuildDialog(builder: AlertDialog.Builder, menu: Menu) {
        builder.setTitle(address)
        MenuInflater(app).inflate(R.menu.iface, menu)
    }

    override fun onMenuItemSelected(item: MenuItem) {
        val ifaceName = address + PROTOCOL_SUFFIX
        when (item.itemId) {
            R.id.menuUseAsServer -> {
                daemonModel.network.callAttr("switch_to_interface", ifaceName)
            }
            R.id.menuDisconnect -> {
                val iface = daemonModel.network.get("interfaces")!!.callAttr("get", ifaceName)
                if (iface != null) {
                    daemonModel.network.callAttr("close_interface", iface)
                }
            }
            else -> throw Exception("Unknown item $item")
        }
    }
}

// Hide the protocol suffix in the UI, but include it in the config setting because the
// back end requires it.
@Suppress("unused")
class ServerPreference: EditTextPreference {
    constructor(context: Context?, attrs: AttributeSet?, defStyleAttr: Int, defStyleRes: Int)
        : super(context, attrs, defStyleAttr, defStyleRes)
    constructor(context: Context?, attrs: AttributeSet?, defStyleAttr: Int)
        : super(context, attrs, defStyleAttr)
    constructor(context: Context?, attrs: AttributeSet?)
        : super(context, attrs)
    constructor(context: Context?)
        : super(context)

    override fun getText(): String {
        var text = super.getText()
        if (text.endsWith(PROTOCOL_SUFFIX)) {
            text = text.dropLast(PROTOCOL_SUFFIX.length)
        }
        return text
    }

    // This method is called with the UI text by the dialog, and with the config text by the
    // base class during startup. So it needs to accept both formats, plus the empty string
    // which means to choose a random server.
    override fun setText(textIn: String) {
        var text = textIn
        if (!text.isEmpty()) {
            if (!text.endsWith(PROTOCOL_SUFFIX)) {
                text += PROTOCOL_SUFFIX
            }
            try {
                libNetwork.callAttr("deserialize_server", text)
            } catch (e: PyException) {
                throw InvalidServerException(e)
            }
        }
        super.setText(text)
    }
}


class ServerPreferenceDialog: EditTextPreferenceDialogFragmentCompat() {
    private lateinit var editText: EditText

    override fun onBindDialogView(view: View) {
        editText = view.findViewById(android.R.id.edit)!!
        editText.setHint(getString(R.string.host) + ":" + getString(R.string.port))
        editText.inputType = InputType.TYPE_CLASS_TEXT + InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        super.onBindDialogView(view)  // Do last: setting inputType resets cursor position.
    }

    override fun onCreateDialog(savedInstanceState: Bundle?): Dialog {
        val dialog = super.onCreateDialog(savedInstanceState) as AlertDialog
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                try {
                    (preference as EditTextPreference).setText(editText.text.toString())
                    onClick(dialog, AlertDialog.BUTTON_POSITIVE)
                    dismiss()
                } catch (e: InvalidServerException) {
                    toast(R.string.Invalid_address, Toast.LENGTH_SHORT)
                }
            }
        }
        return dialog
    }
}


class InvalidServerException(e: Throwable) : IllegalArgumentException(e)