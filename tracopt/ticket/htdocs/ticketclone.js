/** Add ''Clone'' ticket action in ticket comments.
 *
 * The script is added via the tracopt.ticket.clone component.
 *
 * It uses the following Trac global variables:
 *  - form_token (from add_script_data in web.chrome)
 *  - old_values (from add_script_data in ticket.web_ui)
 */

(function($) {
  // retrieve ticket number  (TODO: should be script data)
  var location_groups = /(.*)\/ticket\/(\d+)/.exec(location.href);
  var baseurl = location_groups[1];
  var ticketid = location_groups[2];

  function addField(form, name, value) {
    form.append(
      $.format('<input type="hidden" name="field_$name" value="$value" >', {
        name: name,
        value: value
      }));
  }

  function addCloneAction(container) {
    // the action needs to be wrapped in a <form>, as we want a POST
    var form = $($.format(
      '<form action="$baseurl/newticket" method="post">' +
      ' <div class="inlinebuttons">' +
      '  <input type="submit" name="clone"' +
      '         value="$clone_label" title="$clone_title">' +
      '  <input type="hidden" name="__FORM_TOKEN" value="$form_token">' +
      '  <input type="hidden" name="preview" value="">' +
      ' </div>' +
      '</form>', {
        baseurl: baseurl,
        form_token: form_token,
        clone_label: _("Clone"),
        clone_title: _("Create a new ticket from this comment"),
      }));

    // from ticket's old values, prefill most of the fields for new ticket
    for (var name in old_values) {
      if (name !== 'id' && name !== "summary" && name !== "description"
          && name !== "status" && name !== "resolution") {
        addField(form, name, old_values[name]);
      }
    }

    // for each comment, retrieve comment number and add specific form
    container.each(function() {
      var comment = $('.comment p', $(this).parent()).text();
      if (!comment)
        return;

      var cnum_a_href = $('h3 .cnum a', $(this).parent()).attr('href');

      // clone a specific form for this comment, as we need 2 specific fields
      var cform = form.clone();
      addField(cform, 'summary',
               $.format("(part of #$1) $2", ticketid, old_values['summary']));
      addField(cform, 'description',
               _("Copied from [%(source)s]:\n----\n%(description)s", {
                 source: "ticket:" + ticketid + cnum_a_href,
                 description: comment
               }));
      $(this).prepend(cform);
    });
  }

  $(document).ready(function() {
    if (typeof old_values !== 'undefined') // existing ticket
      addCloneAction($('#changelog .change').has('.cnum')
                     .find('.trac-ticket-buttons'));
  });

})(jQuery);
