define([
    'jquery',
    'backbone',
    'underscore',
    'underscore.string',
    'moment',
    'text!templates/course_list.html',
    'dataTablesBootstrap'
],
    function($,
              Backbone,
              _,
              _s,
              moment,
              courseListViewTemplate) {
        'use strict';

        return Backbone.View.extend({
            className: 'course-list-view',

            template: _.template(courseListViewTemplate),

            renderCourseTable: function() {
                var filterPlaceholder = gettext('Search...'),
                    $emptyLabel = '<label class="sr">' + filterPlaceholder + '</label>';

                if (!$.fn.dataTable.isDataTable('#courseTable')) {
                    var courseTable = this.$el.find('#courseTable').DataTable({
                        serverSide: true,
                        ajax: '/api/v2/courses/?format=datatables',
                        autoWidth: false,
                        lengthMenu: [10, 25, 50, 100],
                        info: true,
                        paging: true,
                        initComplete: function() {
                            $('#courseTable_filter input').unbind()
                            .bind('keyup', function(e) {
                                // If the length is 3 or more characters, or the user pressed ENTER, search
                                if(this.value.length >= 3 || e.keyCode == 13) {
                                    courseTable.search( this.value ).draw();
                                }

                                // Ensure we clear the search if they backspace far enough
                                if(this.value == "") {
                                    courseTable.search("").draw();
                                }
                            });
                        },
                        oLanguage: {
                            oPaginate: {
                                sNext: gettext('Next'),
                                sPrevious: gettext('Previous')
                            },

                            // Translators: _START_, _END_, and _TOTAL_ are placeholders. Do NOT translate them.
                            sInfo: gettext('Displaying _START_ to _END_ of _TOTAL_ courses'),

                            // Translators: _MAX_ is a placeholder. Do NOT translate it.
                            sInfoFiltered: gettext('(filtered from _MAX_ total courses)'),

                            // Translators: _MENU_ is a placeholder. Do NOT translate it.
                            sLengthMenu: gettext('Display _MENU_ courses'),
                            sSearch: ''
                        },
                        order: [[0, 'asc']],
                        columns: [
                            {
                                title: gettext('Course'),
                                data: 'name',
                                fnCreatedCell: function(nTd, sData, oData) {
                                    $(nTd).html(_s.sprintf('<a href="/courses/%s/" class="course-name">%s</a>' +
                                        '<div class="course-id">%s</div>', oData.id, oData.name, oData.id));
                                }
                            },
                            {
                                title: gettext('Course Type'),
                                data: 'type',
                                fnCreatedCell: function(nTd, sData, oData) {
                                    $(nTd).html(_s.capitalize(oData.type));
                                },
                                searchable: false,
                                orderable: false
                            },
                            {
                                title: gettext('Last Edited'),
                                data: 'last_edited',
                                name: 'modified',
                                fnCreatedCell: function(nTd, sData, oData) {
                                    $(nTd).html(moment(oData.last_edited).format('MMMM DD, YYYY, h:mm A'));
                                }
                            },
                            {
                                data: 'id',
                                visible: false,
                                searchable: true
                            }
                        ]
                    });

                    // NOTE: #courseTable_filter is generated by dataTables
                    this.$el.find('#courseTable_filter label').prepend($emptyLabel);

                    this.$el.find('#courseTable_filter input')
                        .attr('placeholder', filterPlaceholder)
                        .addClass('field-input input-text')
                        .removeClass('form-control input-sm');
                }
            },

            render: function() {
                this.$el.html(this.template);
                this.renderCourseTable();

                return this;
            }
        });
    }
);
