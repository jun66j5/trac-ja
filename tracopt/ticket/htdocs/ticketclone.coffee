# Add ''Clone'' ticket action in ticket comments.
#
# The script is added via the tracopt.ticket.clone component.
#
# It uses the following Trac global variables:
#  - from add_script_data in tracopt.ticket.clone: baseurl, ui
#    (TODO: generalize this)
#  - from add_script_data in trac.web.chrome: form_token
#  - from add_script_data in trac.ticket.web_ui:
#     * old_values: {name: value} for each field of the current ticket
#     * changes: list of objects containing the following properties,
#       {author, date, cnum, comment, comment_history, fields, permanent}

$ = jQuery

captionedButton = (symbol, text) ->
  if ui.use_symbols then symbol else "#{symbol} #{text}"

addField = (form, name, value) ->
  form.append $ """
    <input type="hidden" name="field_#{name}" value="#{$.htmlEscape value}">
  """


addCloneAction = (container) ->
  # the action needs to be wrapped in a <form>, as we want a POST
  form = $ """
    <form action="#{baseurl}/newticket" method="post">
     <div class="inlinebuttons">
      <input type="submit" name="clone"
             value="#{captionedButton '+', _ 'Clone'}"
             title="#{_ "Create a new ticket from this comment"}">
      <input type="hidden" name="__FORM_TOKEN" value="#{form_token}">
      <input type="hidden" name="preview" value="">
     </div>
    </form>
  """

  # from ticket's old values, prefill most of the fields for new ticket
  for name, oldvalue of old_values
    addField form, name, oldvalue if name not in [
      "id", "summary", "description", "status", "resolution"
    ]

  # for each comment, retrieve comment number and add specific form
  for [btns, c] in container
    return unless btns.length

    # clone a specific form for this comment, as we need 2 specific fields
    cform = form.clone()
    addField cform, 'summary',
      _ "(part of #%(ticketid)s) %(summary)s",
        ticketid: old_values.id, summary: old_values.summary
    addField cform, 'description',
      _ "Copied from [%(source)s]:\n----\n%(description)s",
        source: "ticket:#{old_values.id}#comment:#{c.cnum}",
        description: c.comment

    btns.prepend cform


commentClone = (chgs) ->
  addCloneAction (for c in chgs
    [$("#trac-change-#{c.cnum}-#{c.date} .trac-ticket-buttons"), c]
  )


$(document).ready () ->
  if old_values? and changes?
    commentClone (c for c in changes when c.cnum? and c.comment and c.permanent)
