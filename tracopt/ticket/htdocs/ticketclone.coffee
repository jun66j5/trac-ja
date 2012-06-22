# Add ''Clone'' ticket action in ticket comments.
#
# The script is added via the tracopt.ticket.clone component.
#
# It uses the following Trac global variables:
#  - form_token (from add_script_data in web.chrome)
#  - old_values (from add_script_data in ticket.web_ui)

$ = jQuery

# retrieve ticket number  (TODO: should be script data)
[_0, baseurl, ticketid] = /(.*)\/ticket\/(\d+)/.exec location.href

addField = (form, name, value) ->
  form.append $ """
    <input type="hidden" name="field_#{name}" value="#{value}">
  """


addCloneAction = (container) ->
  # the action needs to be wrapped in a <form>, as we want a POST
  form = $ """
    <form action="#{baseurl}/newticket" method="post">
     <div class="inlinebuttons">
      <input type="submit" name="clone"
             value="#{_ "Clone"}"
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
  container.each () ->
    comment = $('.comment p', $(this).parent()).text()
    return unless comment

    cnum_a_href = $('h3 .cnum a', $(this).parent()).attr 'href'

    # clone a specific form for this comment, as we need 2 specific fields
    cform = form.clone()
    addField cform, 'summary',
      _ "(part of #%(ticketid)s) %(summary)s",
        ticketid: ticketid, summary: old_values['summary']
    addField cform, 'description',
      _ "Copied from [%(source)s]:\n----\n%(description)s",
        source: "ticket:" + ticketid + cnum_a_href,
        description: comment

    $(this).prepend cform


$(document).ready () ->
  addCloneAction $('#changelog .change').has('.cnum').
    find('.trac-ticket-buttons') if old_values?
